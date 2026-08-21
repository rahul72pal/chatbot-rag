from fastapi import APIRouter, HTTPException, status, Depends

from app.schemas.user import (
    SignupRequest,
    LoginRequest,
    UserResponse,
    TokenResponse,
)

from app.services.auth import (
    signup,
    login,
)


router = APIRouter(
    prefix="/auth",
    tags=["Authentication"]
)


@router.post(
    "/signup",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def signup_user(data: SignupRequest):

    try:

        user = await signup(
            name=data.name,
            email=data.email,
            password=data.password,
        )

        return user

    except ValueError as error:

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        )


from app.core.dependencies import get_current_user
from app.services.auth import delete_user

@router.delete(
    "/me",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete current user",
    description="Deletes the currently authenticated user session along with all custom chatbots they created."
)
async def delete_current_user_account(current_user: dict = Depends(get_current_user)):
    user_id = current_user["id"]
    success = await delete_user(user_id=user_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found or deletion failed."
        )
    return


@router.post(
    "/login",
    response_model=TokenResponse,
)
async def login_user(data: LoginRequest):

    try:

        token = await login(
            email=data.email,
            password=data.password,
        )

        return token

    except ValueError:

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )