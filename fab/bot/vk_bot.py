"""
VK bot module for FAB.

Uses VK Bots Long Poll API (https://dev.vk.com/api/bots-long-poll).
Official library: vk_api, VkBotLongPoll.
"""

import json
import logging
import random
import threading
from typing import Optional

from ..config import config
from ..db.manager import db_manager
from ..db.models import SOURCE_VK
from ..models import access as access_module
from ..utils.mqtt import mqtt_service
from ..utils.ip_utils import is_local_ip
from ..utils.i18n import i18n

logger = logging.getLogger(__name__)

# Lazy import so app starts even if vk_api is missing
vk_api = None
VkApi = None
VkBotLongPoll = None
VkKeyboard = None
VkKeyboardColor = None


def _ensure_vk_api():
    global vk_api, VkApi, VkBotLongPoll, VkKeyboard, VkKeyboardColor
    if VkApi is not None:
        return True
    try:
        import importlib
        _vk_api = importlib.import_module("vk_api")
        _VkBotLongPoll = importlib.import_module("vk_api.bot_longpoll").VkBotLongPoll
        _keyboard = importlib.import_module("vk_api.keyboard")
        vk_api = _vk_api
        VkApi = _vk_api.VkApi
        VkBotLongPoll = _VkBotLongPoll
        VkKeyboard = _keyboard.VkKeyboard
        VkKeyboardColor = _keyboard.VkKeyboardColor
        return True
    except ImportError as e:
        logger.warning("vk_api not installed, VK bot disabled: %s", e)
        return False


def _get_language_for_user(user_id: int, lang_code: Optional[str]) -> str:
    return i18n.detect_language_from_code(lang_code or "")


def _is_authorized(user_id: int) -> bool:
    try:
        return db_manager.is_user_authorized(user_id, SOURCE_VK)
    except Exception as e:
        msg = str(e).lower()
        if "database not initialized" in msg or "closed database" in msg:
            logger.warning("Database temporarily unavailable, denying VK access temporarily")
            return False
        raise


def _is_admin(user_id: int) -> bool:
    return db_manager.is_admin(user_id, SOURCE_VK)


def _keyboard_with_buttons(buttons: list) -> str:
    """Build VK keyboard JSON. buttons: list of rows, each row list of (label, payload)."""
    # VK callback keyboard: buttons[][{"action": {"type": "callback", "label": "...", "payload": "..."}, "color": "primary"}]
    rows = []
    for row in buttons:
        row_buttons = []
        for label, payload in row:
            row_buttons.append({
                "action": {"type": "callback", "label": label[:40], "payload": json.dumps({"cmd": payload})},
                "color": "primary",
            })
        rows.append(row_buttons)
    return json.dumps({"one_time": False, "buttons": rows}, ensure_ascii=False)


def _main_menu_keyboard(language: str, is_admin_user: bool) -> str:
    i18n.set_language(language)
    buttons = [
        [(i18n.get_text("bot.add_access"), "add_access")],
        [(i18n.get_text("bot.my_accesses"), "my_access")],
        [(i18n.get_text("bot.help"), "help")],
    ]
    if is_admin_user:
        buttons.append([(i18n.get_text("bot.manage_users"), "manage_users")])
    if language == "ru":
        buttons.append([("English", "set_language_en")])
    else:
        buttons.append([("Русский", "set_language_ru")])
    return _keyboard_with_buttons(buttons)


class VKBot:
    """VK bot using Bots Long Poll API."""

    def __init__(self) -> None:
        self._vk = None
        self._group_id: Optional[int] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def _get_group_id(self) -> Optional[int]:
        if config.vk_group_id is not None:
            return config.vk_group_id
        try:
            # VK API groups.getById with token returns the group that the token belongs to
            r = self._vk.method("groups.getById", {})
            if r and isinstance(r, list) and len(r) > 0:
                return r[0].get("id")
            return None
        except Exception as e:
            logger.warning("Could not get VK group_id: %s", e)
            return None

    def _send(self, peer_id: int, message: str, keyboard: Optional[str] = None) -> None:
        try:
            params = {
                "peer_id": peer_id,
                "message": message,
                "random_id": random.randint(1, 2**31 - 1),
            }
            if keyboard is not None:
                params["keyboard"] = keyboard
            self._vk.method("messages.send", params)
        except Exception as e:
            logger.error("VK send error [vk]: %s", e)

    def _answer_callback(self, event_id: str, user_id: int, peer_id: int) -> None:
        try:
            self._vk.method("messages.sendMessageEventAnswer", {
                "event_id": event_id,
                "user_id": user_id,
                "peer_id": peer_id,
            })
        except Exception as e:
            logger.error("VK sendMessageEventAnswer error [vk]: %s", e)

    def _handle_message_new(self, event) -> None:
        """Handle message_new event."""
        obj = getattr(event, "object", None) or getattr(event, "obj", None)
        if not obj:
            return
        msg = obj.get("message", {}) if isinstance(obj, dict) else getattr(obj, "message", {})
        if isinstance(msg, dict):
            text = (msg.get("text") or "").strip()
            from_id = msg.get("from_id")
            peer_id = msg.get("peer_id")
        else:
            text = getattr(msg, "text", "") or ""
            from_id = getattr(msg, "from_id", None)
            peer_id = getattr(msg, "peer_id", None)
        if from_id is None or peer_id is None:
            return

        logger.info("User %s [vk] message: %s", from_id, text[:50] if text else "(no text)")

        if not _is_authorized(from_id):
            i18n.set_language(_get_language_for_user(from_id, None))
            self._send(peer_id, i18n.get_text("bot.unauthorized", user_id=from_id))
            return

        language = _get_language_for_user(from_id, None)
        i18n.set_language(language)

        if text in ("/start", "start", "старт", "начать"):
            welcome = i18n.get_text("bot.welcome")
            keyboard = _main_menu_keyboard(language, _is_admin(from_id))
            self._send(peer_id, welcome, keyboard)
            return
        if text in ("/help", "help", "помощь"):
            self._send(peer_id, i18n.get_text("bot.help_text"), _keyboard_with_buttons([
                [(i18n.get_text("bot.main_menu"), "main_menu")],
            ]))
            return

        # Admin: add user by ID (digit)
        if _is_admin(from_id) and text.isdigit():
            try:
                user_id_to_add = int(text)
                db_manager.add_to_whitelist(
                    SOURCE_VK,
                    user_id_to_add,
                    from_id,
                    username=None,
                    first_name=None,
                    last_name=None,
                )
                self._send(peer_id, i18n.get_text("bot.user_added_to_whitelist", user_id=user_id_to_add))
                logger.info("Admin %s [vk] added user %s to whitelist", from_id, user_id_to_add)
            except Exception as e:
                logger.error("Error adding user to whitelist [vk]: %s", e)
                self._send(peer_id, i18n.get_text("bot.error_adding_user"))
            return

        self._send(peer_id, i18n.get_text("bot.use_commands"))

    def _handle_message_event(self, event) -> None:
        """Handle message_event (callback button)."""
        obj = getattr(event, "object", None) or getattr(event, "obj", None)
        if not obj:
            return
        event_id = obj.get("event_id") if isinstance(obj, dict) else getattr(obj, "event_id", None)
        user_id = obj.get("user_id") if isinstance(obj, dict) else getattr(obj, "user_id", None)
        peer_id = obj.get("peer_id") if isinstance(obj, dict) else getattr(obj, "peer_id", None)
        payload_str = obj.get("payload") if isinstance(obj, dict) else getattr(obj, "payload", None)
        if event_id is None or user_id is None or peer_id is None:
            return

        try:
            payload = json.loads(payload_str) if isinstance(payload_str, str) else payload_str or {}
            cmd = payload.get("cmd", "")
        except Exception:
            cmd = ""

        self._answer_callback(str(event_id), user_id, peer_id)

        logger.info("User %s [vk] callback: %s", user_id, cmd)

        if not _is_authorized(user_id):
            i18n.set_language(_get_language_for_user(user_id, None))
            self._send(peer_id, i18n.get_text("bot.unauthorized", user_id=user_id))
            return

        language = _get_language_for_user(user_id, None)
        i18n.set_language(language)

        if cmd == "add_access":
            try:
                session = access_module.access_manager.create_session(
                    user_id, peer_id, config.access_token_expiry, source=SOURCE_VK
                )
                url = f"{config.site_url}/{session.token}"
                text = i18n.get_text("bot.access_link_created", link=url)
                if config.site_backup_url:
                    text += f"\n   {config.site_backup_url.rstrip('/')}/{session.token}"
                self._send(peer_id, text,
                           _keyboard_with_buttons([[(i18n.get_text("bot.main_menu"), "main_menu")]]))
                logger.info("Created access session for user %s [vk]", user_id)
            except Exception as e:
                logger.error("Error creating access link [vk]: %s", e)
                self._send(peer_id, i18n.get_text("bot.error", error="Failed to create access link"),
                           _keyboard_with_buttons([[(i18n.get_text("bot.main_menu"), "main_menu")]]))

        elif cmd == "my_access":
            try:
                active_requests = access_module.access_manager.get_active_requests_for_user(
                    user_id, source=SOURCE_VK
                )
                if not active_requests:
                    self._send(peer_id, i18n.get_text("bot.no_active_accesses"),
                               _keyboard_with_buttons([
                                   [(i18n.get_text("bot.add_access"), "add_access")],
                                   [(i18n.get_text("bot.main_menu"), "main_menu")],
                               ]))
                else:
                    lines = [i18n.get_text("bot.active_accesses_title") + "\n\n"]
                    buttons = []
                    for i, req in enumerate(active_requests, 1):
                        dur_h = req.duration // 3600
                        lines.append(
                            f"{i}. {i18n.get_text('bot.access_opened', hours=i18n.format_duration(dur_h))}\n"
                            f"   IP: {req.ip_address or i18n.get_text('web.unknown')}\n"
                            f"   {i18n.get_text('web.created')}: {req.created_at.strftime('%d.%m.%Y %H:%M:%S')}\n"
                        )
                        buttons.append([(i18n.get_text("bot.close_access", number=i), f"close_access_{req.id}")])
                    buttons.append([(i18n.get_text("bot.main_menu"), "main_menu")])
                    self._send(peer_id, "\n".join(lines), _keyboard_with_buttons(buttons))
            except Exception as e:
                logger.error("Error fetching accesses [vk]: %s", e)
                self._send(peer_id, i18n.get_text("bot.error", error="Failed to fetch access information"),
                           _keyboard_with_buttons([[(i18n.get_text("bot.main_menu"), "main_menu")]]))

        elif cmd == "help":
            self._send(peer_id, i18n.get_text("bot.help_text"),
                       _keyboard_with_buttons([[(i18n.get_text("bot.main_menu"), "main_menu")]]))

        elif cmd == "main_menu":
            self._send(peer_id, i18n.get_text("bot.welcome"),
                       _main_menu_keyboard(language, _is_admin(user_id)))

        elif cmd == "manage_users":
            if not _is_admin(user_id):
                self._send(peer_id, "Access denied")
                return
            self._send(peer_id, i18n.get_text("bot.admin_menu"),
                       _keyboard_with_buttons([
                           [(i18n.get_text("bot.add_user"), "add_user")],
                           [(i18n.get_text("bot.list_users"), "list_users")],
                           [(i18n.get_text("bot.main_menu"), "main_menu")],
                       ]))

        elif cmd == "add_user":
            if not _is_admin(user_id):
                self._send(peer_id, "Access denied")
                return
            self._send(peer_id, i18n.get_text("bot.add_user_prompt"),
                       _keyboard_with_buttons([[(i18n.get_text("bot.back"), "manage_users")]]))

        elif cmd == "list_users":
            if not _is_admin(user_id):
                self._send(peer_id, "Access denied")
                return
            try:
                users = db_manager.get_whitelist_users(SOURCE_VK)
                if not users:
                    self._send(peer_id, i18n.get_text("bot.no_users_in_whitelist"),
                               _keyboard_with_buttons([
                                   [(i18n.get_text("bot.add_user"), "add_user")],
                                   [(i18n.get_text("bot.back"), "manage_users")],
                               ]))
                else:
                    lines = [i18n.get_text("bot.whitelist_users_title") + "\n\n"]
                    buttons = []
                    for i, u in enumerate(users, 1):
                        lines.append(
                            f"{i}. ID: {u.telegram_user_id}\n"
                            f"   {i18n.get_text('bot.name')}: {u.first_name or ''} {u.last_name or ''}\n"
                            f"   {i18n.get_text('bot.added')}: {u.created_at.strftime('%d.%m.%Y')}\n"
                        )
                        buttons.append([(i18n.get_text("bot.remove_user", number=i), f"remove_user_{u.telegram_user_id}")])
                    buttons.append([(i18n.get_text("bot.back"), "manage_users")])
                    self._send(peer_id, "\n".join(lines), _keyboard_with_buttons(buttons))
            except Exception as e:
                logger.error("Error listing users [vk]: %s", e)
                self._send(peer_id, "Error listing users")

        elif cmd.startswith("remove_user_"):
            if not _is_admin(user_id):
                self._send(peer_id, "Access denied")
                return
            try:
                to_remove = int(cmd.replace("remove_user_", ""))
                ok = db_manager.remove_from_whitelist(SOURCE_VK, to_remove)
                if ok:
                    self._send(peer_id, i18n.get_text("bot.user_removed", user_id=to_remove))
                    logger.info("Admin %s [vk] removed user %s from whitelist", user_id, to_remove)
                else:
                    self._send(peer_id, i18n.get_text("bot.user_not_found"))
                self._send(peer_id, i18n.get_text("bot.main_menu"),
                           _keyboard_with_buttons([
                               [(i18n.get_text("bot.list_users"), "list_users")],
                               [(i18n.get_text("bot.back"), "manage_users")],
                           ]))
            except Exception as e:
                logger.error("Error removing user [vk]: %s", e)

        elif cmd.startswith("close_access_"):
            access_id = cmd.replace("close_access_", "")
            try:
                request = access_module.access_manager.close_access_request(access_id)
                if request and request.telegram_user_id == user_id:
                    try:
                        ip_obj = __import__("ipaddress").ip_address(request.ip_address or "127.0.0.1")
                    except Exception:
                        ip_obj = __import__("ipaddress").ip_address("127.0.0.1")
                    ip_excluded = is_local_ip(request.ip_address) or any(
                        ip_obj in net for net in getattr(config, "exclude_networks", [])
                    )
                    if not ip_excluded and request.ip_address:
                        mqtt_service.publish_whitelist_close(request.ip_address)
                    self._send(peer_id, i18n.get_text(
                        "bot.access_closed",
                        ip=request.ip_address or i18n.get_text("web.unknown"),
                        created=request.created_at.strftime("%H:%M:%S"),
                        closed=request.closed_at.strftime("%H:%M:%S"),
                    ))
                    logger.info("Access %s closed by user %s [vk]", access_id, user_id)
                else:
                    self._send(peer_id, i18n.get_text("bot.access_not_found"))
                keyboard = _keyboard_with_buttons([
                    [(i18n.get_text("bot.my_accesses"), "my_access")],
                    [(i18n.get_text("bot.main_menu"), "main_menu")],
                ])
                self._send(peer_id, i18n.get_text("bot.main_menu"), keyboard)
            except Exception as e:
                logger.error("Error closing access [vk]: %s", e)
                self._send(peer_id, i18n.get_text("bot.error", error="Failed to close access"))

        elif cmd in ("set_language_ru", "set_language_en"):
            lang = "ru" if "ru" in cmd else "en"
            i18n.set_language(lang)
            self._send(peer_id, i18n.get_text("bot.welcome"),
                       _main_menu_keyboard(lang, _is_admin(user_id)))
            logger.info("User %s [vk] changed language to %s", user_id, lang)

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                for event in self._long_poll.check():
                    if self._stop.is_set():
                        break
                    try:
                        t = getattr(event, "type", None) or getattr(event, "t", None)
                        if t == "message_new":
                            self._handle_message_new(event)
                        elif t == "message_event":
                            self._handle_message_event(event)
                    except Exception as e:
                        logger.error("VK event handler error [vk]: %s", e, exc_info=True)
            except Exception as e:
                if not self._stop.is_set():
                    logger.warning("VK Long Poll error [vk]: %s", e)
                break

    def start(self) -> bool:
        """Start VK bot in a background thread. Returns True if started, False if skipped or failed (no crash)."""
        if not getattr(config, "vk_enabled", False):
            logger.info("VK bot disabled (VK_ENABLED=false), skipping")
            return False
        if not config.vk_bot_token:
            logger.info("VK bot token not set, skipping VK bot")
            return False
        if not _ensure_vk_api():
            return False
        try:
            session = None
            if config.vk_api_proxy:
                requests_mod = __import__("requests")
                session = requests_mod.Session()
                session.proxies = {"http": config.vk_api_proxy, "https": config.vk_api_proxy}
            self._vk = VkApi(token=config.vk_bot_token, session=session) if session else VkApi(token=config.vk_bot_token)
            self._group_id = self._get_group_id()
            if self._group_id is None:
                logger.warning("VK group_id not set and could not be obtained; set VK_GROUP_ID. Skipping VK bot.")
                return False
            self._long_poll = VkBotLongPoll(self._vk, self._group_id, wait=25)
            self._stop.clear()
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()
            logger.info("VK bot started [vk] (group_id=%s)", self._group_id)
            return True
        except Exception as e:
            logger.warning("VK bot failed to start (app continues): %s", e, exc_info=False)
            return False

    def stop(self) -> None:
        """Stop VK bot."""
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        self._thread = None
        self._vk = None
        self._group_id = None
        logger.info("VK bot stopped")


def create_vk_bot() -> VKBot:
    return VKBot()
