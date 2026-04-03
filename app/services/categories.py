import uuid

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.transaction import Category
from app.models.user import User
from app.schemas.category import CategoryCreate, CategoryResponse


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
    if data.type not in ("expense", "income", "both"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="type must be expense, income or both")

    category = Category(
        user_id=user.id,
        name=data.name,
        icon=data.icon,
        color=data.color,
        type=data.type,
    )
    db.add(category)
    await db.flush()
    return CategoryResponse.model_validate(category)


async def delete_category(category_id: uuid.UUID, user: User, db: AsyncSession) -> None:
    result = await db.execute(
        select(Category).where(Category.id == category_id, Category.user_id == user.id)
    )
    category = result.scalar_one_or_none()
    if not category:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")

    category.is_active = False
