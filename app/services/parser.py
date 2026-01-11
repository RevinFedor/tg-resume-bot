import httpx
from bs4 import BeautifulSoup
from dataclasses import dataclass
from datetime import datetime
import logging
import asyncio
import random

logger = logging.getLogger(__name__)


@dataclass
class ParsedPost:
    post_id: int
    content: str
    date: datetime | None
    views: str | None
    images: list[str]


@dataclass
class ChannelInfo:
    username: str
    title: str | None
    description: str | None
    subscribers: str | None
    photo_url: str | None


class ChannelParser:
    """Парсер публичных Telegram каналов через t.me/s/"""

    BASE_URL = "https://t.me/s"
    TIMEOUT = 10.0

    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=self.TIMEOUT,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            },
            follow_redirects=True,
        )

    async def close(self):
        await self.client.aclose()

    async def get_channel_info(self, username: str) -> ChannelInfo | None:
        """Получает информацию о канале"""
        try:
            # Добавляем случайную задержку для избежания rate limit
            await asyncio.sleep(random.uniform(0.5, 1.5))

            url = f"https://t.me/{username}"
            response = await self.client.get(url)

            if response.status_code != 200:
                logger.warning(f"Failed to fetch channel info for {username}: {response.status_code}")
                return None

            soup = BeautifulSoup(response.text, "html.parser")

            # Извлекаем данные из OpenGraph тегов
            title = None
            description = None
            photo_url = None

            og_title = soup.find("meta", property="og:title")
            if og_title:
                title = og_title.get("content")

            og_description = soup.find("meta", property="og:description")
            if og_description:
                description = og_description.get("content")

            og_image = soup.find("meta", property="og:image")
            if og_image:
                photo_url = og_image.get("content")

            # Количество подписчиков
            subscribers = None
            subs_elem = soup.find("div", class_="tgme_page_extra")
            if subs_elem:
                subscribers = subs_elem.text.strip()

            return ChannelInfo(
                username=username,
                title=title,
                description=description,
                subscribers=subscribers,
                photo_url=photo_url,
            )

        except Exception as e:
            logger.error(f"Error fetching channel info for {username}: {e}")
            return None

    async def get_posts(self, username: str, after_post_id: int = 0) -> list[ParsedPost]:
        """Получает посты из канала"""
        try:
            # Добавляем случайную задержку
            await asyncio.sleep(random.uniform(0.5, 1.5))

            # Добавляем timestamp для обхода кэша
            url = f"{self.BASE_URL}/{username}?_={int(datetime.now().timestamp())}"
            response = await self.client.get(url)

            if response.status_code != 200:
                logger.warning(f"Failed to fetch posts for {username}: {response.status_code}")
                return []

            soup = BeautifulSoup(response.text, "html.parser")
            posts = []

            # Парсим все сообщения
            for msg in soup.find_all("div", class_="tgme_widget_message"):
                try:
                    # Извлекаем ID поста
                    data_post = msg.get("data-post", "")
                    if "/" not in data_post:
                        continue

                    post_id = int(data_post.split("/")[1])

                    # Пропускаем старые посты
                    if post_id <= after_post_id:
                        continue

                    # Текст сообщения
                    text_elem = msg.find("div", class_="tgme_widget_message_text")
                    content = text_elem.get_text(strip=True) if text_elem else ""

                    # Дата
                    date = None
                    time_elem = msg.find("time", class_="datetime")
                    if time_elem and time_elem.get("datetime"):
                        try:
                            date = datetime.fromisoformat(time_elem["datetime"].replace("Z", "+00:00"))
                        except ValueError:
                            pass

                    # Просмотры
                    views = None
                    views_elem = msg.find("span", class_="tgme_widget_message_views")
                    if views_elem:
                        views = views_elem.text.strip()

                    # Изображения
                    images = []
                    for img in msg.find_all("a", class_="tgme_widget_message_photo_wrap"):
                        style = img.get("style", "")
                        if "background-image" in style:
                            # Извлекаем URL из style="background-image:url('...')"
                            start = style.find("url('") + 5
                            end = style.find("')", start)
                            if start > 4 and end > start:
                                images.append(style[start:end])

                    if content:  # Только посты с текстом
                        posts.append(ParsedPost(
                            post_id=post_id,
                            content=content,
                            date=date,
                            views=views,
                            images=images,
                        ))

                except Exception as e:
                    logger.error(f"Error parsing post: {e}")
                    continue

            # Сортируем по ID (новые первые)
            posts.sort(key=lambda p: p.post_id, reverse=True)

            logger.info(f"Parsed {len(posts)} new posts from @{username}")
            return posts

        except Exception as e:
            logger.error(f"Error fetching posts for {username}: {e}")
            return []

    async def is_channel_public(self, username: str) -> bool:
        """Проверяет, публичный ли канал"""
        try:
            url = f"{self.BASE_URL}/{username}"
            response = await self.client.get(url)
            return response.status_code == 200
        except Exception:
            return False
