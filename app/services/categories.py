import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.telegram import fmt_first_category, notify
from app.models.transaction import Category
from app.models.user import User
from app.schemas.category import CategoryCreate, CategoryResponse, CategoryUpdate


async def get_categories(user: User, db: AsyncSession) -> list[CategoryResponse]:
    result = await db.execute(
        select(Category)
        .where(
            or_(Category.user_id == user.id, Category.user_id.is_(None)),
            Category.is_active == True,
        )
        .order_by(Category.user_id.is_(None).desc(), Category.sort_order)
    )
    categories = result.scalars().all()
    return [CategoryResponse.model_validate(c) for c in categories]


async def create_category(data: CategoryCreate, user: User, db: AsyncSession) -> CategoryResponse:
    count_result = await db.execute(
        select(func.count()).select_from(Category).where(
            Category.user_id == user.id, Category.is_active == True
        )
    )
    is_first = count_result.scalar() == 0

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
        )
    )
    category = result.scalar_one_or_none()
    if not category:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")

    category.is_active = False
