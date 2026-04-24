import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.telegram import fmt_first_category, notify
from app.models.transaction import Category
from app.models.user import User
from app.schemas.category import CategoryCreate, CategoryResponse, CategoryUpdate
from app.services.subscriptions import is_effective_pro

# Free users can create at most this many brand-new user categories
# (copies/overrides of system categories do not count).
FREE_USER_CATEGORY_LIMIT = 5


async def get_categories(user: User, db: AsyncSession) -> list[CategoryResponse]:
    # Получаем все пользовательские + системные категории
    result = await db.execute(
        select(Category)
        .where(
            or_(Category.user_id == user.id, Category.user_id.is_(None)),
            Category.is_active == True,
        )
        .order_by(Category.user_id.is_(None).desc(), Category.sort_order)
    )
    all_cats = result.scalars().all()

    # Если у пользователя есть копия системной (parent_id != None),
    # скрываем оригинал
    overridden_ids = {c.parent_id for c in all_cats if c.parent_id is not None}
    filtered = [c for c in all_cats if c.id not in overridden_ids]

    return [CategoryResponse.model_validate(c) for c in filtered]


async def create_category(data: CategoryCreate, user: User, db: AsyncSession) -> CategoryResponse:
    # Count only brand-new user categories (parent_id is NULL). Overrides of
    # system categories are tracked separately and don't count toward the
    # Free-plan limit.
    count_result = await db.execute(
        select(func.count()).select_from(Category).where(
            Category.user_id == user.id,
            Category.parent_id.is_(None),
            Category.is_active == True,
        )
    )
    existing_count = count_result.scalar() or 0
    if existing_count >= FREE_USER_CATEGORY_LIMIT and not is_effective_pro(user.subscription):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Free-план: максимум {FREE_USER_CATEGORY_LIMIT} "
                "пользовательских категорий. Оформите Pro для безлимита."
            ),
        )
    is_first = existing_count == 0

    category = Category(
        user_id=user.id,
        name=data.name,
        icon=data.icon,
        color=data.color,
        type=data.type,
    )
    db.add(category)
    await db.flush()

    if is_first:
        await notify(fmt_first_category(user.email, data.name))

    return CategoryResponse.model_validate(category)


async def update_category(category_id: uuid.UUID, data: CategoryUpdate, user: User, db: AsyncSession) -> CategoryResponse:
    result = await db.execute(
        select(Category).where(
            Category.id == category_id,
            or_(Category.user_id == user.id, Category.user_id.is_(None)),
            Category.is_active == True,
        )
    )
    category = result.scalar_one_or_none()
    if not category:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")

    # Системная категория — copy-on-write
    if category.user_id is None:
        # Проверяем нет ли уже копии
        existing = await db.execute(
            select(Category).where(
                Category.parent_id == category.id,
                Category.user_id == user.id,
            )
        )
        copy = existing.scalar_one_or_none()
        if copy:
            # Обновляем существующую копию
            for field, value in data.model_dump(exclude_unset=True).items():
                setattr(copy, field, value)
            copy.is_active = True
            await db.flush()
            return CategoryResponse.model_validate(copy)

        # Создаём новую копию
        update_data = data.model_dump(exclude_unset=True)
        copy = Category(
            user_id=user.id,
            parent_id=category.id,
            name=update_data.get("name", category.name),
            icon=update_data.get("icon", category.icon),
            color=update_data.get("color", category.color),
            type=update_data.get("type", category.type),
            sort_order=category.sort_order,
        )
        db.add(copy)
        await db.flush()
        return CategoryResponse.model_validate(copy)

    # Пользовательская категория — обновляем напрямую
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(category, field, value)

    await db.flush()
    return CategoryResponse.model_validate(category)


async def restore_category(category_id: uuid.UUID, user: User, db: AsyncSession) -> CategoryResponse:
    result = await db.execute(
        select(Category).where(
            Category.id == category_id,
            Category.user_id == user.id,
            Category.is_active == False,
        )
    )
    category = result.scalar_one_or_none()
    if not category:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deleted category not found")
    category.is_active = True
    await db.flush()
    return CategoryResponse.model_validate(category)


async def delete_category(category_id: uuid.UUID, user: User, db: AsyncSession) -> None:
    result = await db.execute(
        select(Category).where(
            Category.id == category_id,
            or_(Category.user_id == user.id, Category.user_id.is_(None)),
            Category.is_active == True,
        )
    )
    category = result.scalar_one_or_none()
    if not category:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")

    # Системная — создаём скрытую копию для пользователя
    if category.user_id is None:
        existing = await db.execute(
            select(Category).where(
                Category.parent_id == category.id,
                Category.user_id == user.id,
            )
        )
        copy = existing.scalar_one_or_none()
        if copy:
            copy.is_active = False
        else:
            copy = Category(
                user_id=user.id,
                parent_id=category.id,
                name=category.name,
                icon=category.icon,
                color=category.color,
                type=category.type,
                sort_order=category.sort_order,
                is_active=False,
            )
            db.add(copy)
        return

    category.is_active = False
