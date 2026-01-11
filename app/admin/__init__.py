from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from starlette.requests import Request
from starlette.responses import RedirectResponse
import os

from app.db.models import User, Channel, Subscription, Post


class AdminAuth(AuthenticationBackend):
    """Простая авторизация для админки"""

    async def login(self, request: Request) -> bool:
        form = await request.form()
        password = form.get("password")

        admin_password = os.getenv("ADMIN_PASSWORD", "admin123")

        if password == admin_password:
            request.session.update({"authenticated": True})
            return True
        return False

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        return request.session.get("authenticated", False)


class UserAdmin(ModelView, model=User):
    column_list = [User.id, User.telegram_id, User.username, User.first_name, User.is_admin, User.created_at]
    column_searchable_list = [User.telegram_id, User.username]
    column_sortable_list = [User.id, User.created_at]
    column_default_sort = [(User.created_at, True)]
    can_create = False
    can_delete = True
    can_edit = True
    name = "User"
    name_plural = "Users"
    icon = "fa-solid fa-user"


class ChannelAdmin(ModelView, model=Channel):
    column_list = [Channel.id, Channel.username, Channel.title, Channel.is_active, Channel.last_post_id, Channel.last_checked_at]
    column_searchable_list = [Channel.username, Channel.title]
    column_sortable_list = [Channel.id, Channel.created_at, Channel.last_checked_at]
    column_default_sort = [(Channel.created_at, True)]
    can_create = True
    can_delete = True
    can_edit = True
    name = "Channel"
    name_plural = "Channels"
    icon = "fa-solid fa-broadcast-tower"


class SubscriptionAdmin(ModelView, model=Subscription):
    column_list = [Subscription.id, Subscription.user_id, Subscription.channel_id, Subscription.created_at]
    column_sortable_list = [Subscription.id, Subscription.created_at]
    column_default_sort = [(Subscription.created_at, True)]
    can_create = True
    can_delete = True
    can_edit = False
    name = "Subscription"
    name_plural = "Subscriptions"
    icon = "fa-solid fa-bell"


class PostAdmin(ModelView, model=Post):
    column_list = [Post.id, Post.channel_id, Post.post_id, Post.created_at]
    column_searchable_list = [Post.content, Post.summary]
    column_sortable_list = [Post.id, Post.created_at]
    column_default_sort = [(Post.created_at, True)]
    can_create = False
    can_delete = True
    can_edit = False
    name = "Post"
    name_plural = "Posts"
    icon = "fa-solid fa-newspaper"

    # Показываем полный текст в деталях
    column_details_list = [Post.id, Post.channel_id, Post.post_id, Post.content, Post.summary, Post.created_at]


def setup_admin(app, engine):
    """Настраивает SQLAdmin"""
    authentication_backend = AdminAuth(secret_key=os.getenv("SECRET_KEY", "secret"))

    admin = Admin(
        app,
        engine,
        authentication_backend=authentication_backend,
        title="Channel Resume Bot",
    )

    admin.add_view(UserAdmin)
    admin.add_view(ChannelAdmin)
    admin.add_view(SubscriptionAdmin)
    admin.add_view(PostAdmin)

    return admin
