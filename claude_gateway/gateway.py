"""Telegram Gateway for Claude Code - Main bot application."""

import asyncio
import logging
import os
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.constants import ParseMode

from .config import (
    BOT_TOKEN,
    ALLOWED_CHAT_IDS,
    DEFAULT_PROJECT_PATH,
    PROJECT_SEARCH_DIRS,
    NEW_PROJECT_DIR,
    CHUNK_SEND_INTERVAL,
    MAX_MESSAGE_LENGTH,
)
from .claude_runner import runner

# Set up logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Session state per chat
chat_sessions: dict[int, dict] = {}


def get_session(chat_id: int) -> dict:
    """Get or create a session for a chat."""
    if chat_id not in chat_sessions:
        chat_sessions[chat_id] = {
            "working_dir": DEFAULT_PROJECT_PATH,
            "has_conversation": False,
        }
    return chat_sessions[chat_id]


def is_authorized(chat_id: int) -> bool:
    """Check if a chat ID is authorized."""
    if not ALLOWED_CHAT_IDS:
        # If no whitelist configured, deny all
        return False
    return chat_id in ALLOWED_CHAT_IDS


async def unauthorized_response(update: Update) -> None:
    """Send unauthorized message."""
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        f"Unauthorized. Your chat ID is: `{chat_id}`\n\n"
        "Add this to ALLOWED_CHAT_IDS in your config to authorize.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    if not is_authorized(update.effective_chat.id):
        await unauthorized_response(update)
        return

    session = get_session(update.effective_chat.id)
    await update.message.reply_text(
        "Welcome to the Claude Code Gateway!\n\n"
        "Send me any message and I'll forward it to Claude Code.\n"
        "Follow-up messages automatically continue the conversation.\n\n"
        "*Commands:*\n"
        "/new - Start a fresh conversation\n"
        "/project - Select or change project\n"
        "/newproject <name> - Create a new project\n"
        "/status - Show current session info\n"
        "/stop - Cancel current Claude operation\n"
        "/help - Show this help message\n\n"
        f"Current project: `{session['working_dir']}`",
        parse_mode=ParseMode.MARKDOWN,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    if not is_authorized(update.effective_chat.id):
        await unauthorized_response(update)
        return

    await update.message.reply_text(
        "*Available Commands:*\n\n"
        "/new - Start a fresh conversation\n"
        "/start - Welcome message\n"
        "/project - Select or change project\n"
        "/newproject <name> - Create a new project\n"
        "/status - Show current project and session info\n"
        "/stop - Cancel the current Claude operation\n"
        "/help - Show this help message\n\n"
        "*Usage:*\n"
        "Simply send any message to interact with Claude Code. "
        "Follow-up messages automatically continue the conversation. "
        "Use /new to start fresh.",
        parse_mode=ParseMode.MARKDOWN,
    )


def find_project(name: str) -> str | None:
    """Search PROJECT_SEARCH_DIRS for a directory matching name."""
    for search_dir in PROJECT_SEARCH_DIRS:
        candidate = os.path.join(search_dir, name)
        if os.path.isdir(candidate):
            return os.path.realpath(candidate)
    return None


def list_projects() -> list[tuple[str, str]]:
    """List all available projects as (name, full_path) tuples."""
    projects = []
    for search_dir in PROJECT_SEARCH_DIRS:
        if not os.path.isdir(search_dir):
            continue
        for entry in sorted(os.listdir(search_dir)):
            full = os.path.join(search_dir, entry)
            if os.path.isdir(full):
                projects.append((entry, os.path.realpath(full)))
    return projects


def build_project_keyboard() -> InlineKeyboardMarkup:
    """Build inline keyboard with project buttons."""
    projects = list_projects()
    # Find duplicate names to disambiguate
    name_counts: dict[str, int] = {}
    for name, _ in projects:
        name_counts[name] = name_counts.get(name, 0) + 1
    buttons = []
    for name, full_path in projects:
        if name_counts[name] > 1:
            # Show parent dir to disambiguate (e.g. "gateway (~/claude)")
            parent = os.path.dirname(full_path)
            short_parent = parent.replace(os.path.expanduser("~"), "~")
            label = f"{name} ({short_parent})"
        else:
            label = name
        buttons.append(
            [InlineKeyboardButton(label, callback_data=f"project:{full_path}")]
        )
    return InlineKeyboardMarkup(buttons)


async def project_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline keyboard button press for project selection."""
    query = update.callback_query
    if not is_authorized(query.from_user.id):
        await query.answer("Unauthorized.")
        return

    path = query.data.removeprefix("project:")
    valid, result = runner.validate_path(path)
    if not valid:
        await query.answer(f"Invalid path: {result}")
        return

    chat_id = query.message.chat_id
    session = get_session(chat_id)
    session["working_dir"] = result
    session["has_conversation"] = False

    await query.answer(f"Switched to {os.path.basename(result)}")
    await query.edit_message_text(
        f"Project changed to: `{result}`",
        parse_mode=ParseMode.MARKDOWN,
    )


async def project_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /project command to change working directory."""
    if not is_authorized(update.effective_chat.id):
        await unauthorized_response(update)
        return

    if not context.args:
        session = get_session(update.effective_chat.id)
        keyboard = build_project_keyboard()
        await update.message.reply_text(
            f"Current project: `{session['working_dir']}`\n\n"
            "Select a project:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard,
        )
        return

    name = " ".join(context.args)

    # Search in project directories first
    found = find_project(name)
    if found:
        valid, result = runner.validate_path(found)
        if not valid:
            await update.message.reply_text(f"Invalid path: {result}")
            return
        session = get_session(update.effective_chat.id)
        session["working_dir"] = result
        session["has_conversation"] = False
        await update.message.reply_text(
            f"Project changed to: `{result}`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Fall back to treating it as a full path
    valid, result = runner.validate_path(name)
    if not valid:
        await update.message.reply_text(
            f"Project `{name}` not found.\n\n"
            "Searched in:\n"
            + "\n".join(f"- `{d}`" for d in PROJECT_SEARCH_DIRS),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    session = get_session(update.effective_chat.id)
    session["working_dir"] = result
    session["has_conversation"] = False
    await update.message.reply_text(
        f"Project changed to: `{result}`",
        parse_mode=ParseMode.MARKDOWN,
    )


async def newproject_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /newproject command to create a new project directory."""
    if not is_authorized(update.effective_chat.id):
        await unauthorized_response(update)
        return

    if not context.args:
        await update.message.reply_text(
            f"Usage: /newproject <name>\n\n"
            f"Creates a new project in `{NEW_PROJECT_DIR}`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    name = " ".join(context.args)

    # Sanitize: only allow simple directory names
    if "/" in name or "\\" in name or name.startswith("."):
        await update.message.reply_text("Invalid project name. Use a simple name without paths or leading dots.")
        return

    project_path = os.path.join(NEW_PROJECT_DIR, name)
    if os.path.exists(project_path):
        await update.message.reply_text(
            f"Project `{name}` already exists at `{project_path}`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    try:
        os.makedirs(project_path)
    except OSError as e:
        await update.message.reply_text(f"Failed to create project: {e}")
        return

    session = get_session(update.effective_chat.id)
    session["working_dir"] = project_path
    session["has_conversation"] = False
    await update.message.reply_text(
        f"Created and switched to: `{project_path}`",
        parse_mode=ParseMode.MARKDOWN,
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status command."""
    if not is_authorized(update.effective_chat.id):
        await unauthorized_response(update)
        return

    chat_id = update.effective_chat.id
    session = get_session(chat_id)
    is_running = runner.is_running(str(chat_id))

    await update.message.reply_text(
        "*Session Status:*\n\n"
        f"Chat ID: `{chat_id}`\n"
        f"Project: `{session['working_dir']}`\n"
        f"Claude running: {'Yes' if is_running else 'No'}",
        parse_mode=ParseMode.MARKDOWN,
    )


async def new_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /new command to start a fresh Claude conversation."""
    if not is_authorized(update.effective_chat.id):
        await unauthorized_response(update)
        return

    chat_id = update.effective_chat.id
    session = get_session(chat_id)
    session["has_conversation"] = False
    await update.message.reply_text("New conversation started. Next message will begin a fresh session.")


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /stop command to cancel current Claude operation."""
    if not is_authorized(update.effective_chat.id):
        await unauthorized_response(update)
        return

    chat_id = update.effective_chat.id
    if await runner.stop(str(chat_id)):
        await update.message.reply_text("Claude operation cancelled.")
    else:
        await update.message.reply_text("No active Claude operation to cancel.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle regular messages - forward to Claude."""
    if not is_authorized(update.effective_chat.id):
        await unauthorized_response(update)
        return

    chat_id = update.effective_chat.id
    message_text = update.message.text

    if not message_text:
        return

    session = get_session(chat_id)
    working_dir = session["working_dir"]

    # Send initial "thinking" message
    response_message = await update.message.reply_text(
        "_Running Claude..._",
        parse_mode=ParseMode.MARKDOWN,
    )

    # Collect and stream output
    full_output = ""
    last_update_time = 0
    chunk_buffer = ""
    continue_conversation = session["has_conversation"]

    async for chunk in runner.run(str(chat_id), message_text, working_dir, continue_conversation):
        chunk_buffer += chunk
        current_time = asyncio.get_event_loop().time()

        # Update message periodically or when buffer is large enough
        should_update = (
            current_time - last_update_time >= CHUNK_SEND_INTERVAL
            or len(chunk_buffer) >= 1000
        )

        if should_update and chunk_buffer:
            full_output += chunk_buffer
            chunk_buffer = ""
            last_update_time = current_time

            # Truncate for display if needed
            display_text = full_output
            if len(display_text) > MAX_MESSAGE_LENGTH:
                display_text = "..." + display_text[-(MAX_MESSAGE_LENGTH - 3):]

            try:
                await response_message.edit_text(display_text)
            except Exception as e:
                # Message might be unchanged or rate limited
                logger.debug(f"Could not update message: {e}")

    # Final update with any remaining buffer
    if chunk_buffer:
        full_output += chunk_buffer

    if not full_output:
        full_output = "_No output from Claude._"
    else:
        # Mark that we have an active conversation for --continue on next message
        session["has_conversation"] = True

    # Send final output - may need to split into multiple messages
    if len(full_output) <= MAX_MESSAGE_LENGTH:
        try:
            await response_message.edit_text(full_output)
        except Exception:
            pass
    else:
        # Delete the updating message and send as multiple messages
        try:
            await response_message.delete()
        except Exception:
            pass

        # Split into chunks
        chunks = []
        remaining = full_output
        while remaining:
            if len(remaining) <= MAX_MESSAGE_LENGTH:
                chunks.append(remaining)
                break
            # Find a good split point (newline or space)
            split_at = MAX_MESSAGE_LENGTH
            for sep in ["\n", " "]:
                last_sep = remaining[:MAX_MESSAGE_LENGTH].rfind(sep)
                if last_sep > MAX_MESSAGE_LENGTH // 2:
                    split_at = last_sep + 1
                    break
            chunks.append(remaining[:split_at])
            remaining = remaining[split_at:]

        for i, chunk in enumerate(chunks):
            prefix = f"*[Part {i + 1}/{len(chunks)}]*\n" if len(chunks) > 1 else ""
            await update.message.reply_text(
                prefix + chunk,
                parse_mode=ParseMode.MARKDOWN if prefix else None,
            )


async def _download_and_notify(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    file_id: str,
    filename: str,
) -> None:
    """Download a Telegram file to the session's working dir and notify the user."""
    chat_id = update.effective_chat.id
    session = get_session(chat_id)
    working_dir = session["working_dir"]
    dest_path = os.path.join(working_dir, filename)

    status_msg = await update.message.reply_text(
        "_Downloading image..._",
        parse_mode=ParseMode.MARKDOWN,
    )

    try:
        tg_file = await context.bot.get_file(file_id)
        await tg_file.download_to_drive(dest_path)
    except Exception as e:
        await status_msg.edit_text(f"Failed to download image: {e}")
        return

    caption = update.message.caption or ""
    await status_msg.edit_text(
        f"Image saved to `{dest_path}`" + (f"\n\nCaption: _{caption}_" if caption else ""),
        parse_mode=ParseMode.MARKDOWN,
    )

    # If there's a caption, also forward it to Claude with context about the file
    if caption:
        prompt = f"I uploaded an image to `{dest_path}`. {caption}"
        response_message = await update.message.reply_text(
            "_Running Claude..._",
            parse_mode=ParseMode.MARKDOWN,
        )

        full_output = ""
        last_update_time = 0
        chunk_buffer = ""
        continue_conversation = session["has_conversation"]

        async for chunk in runner.run(str(chat_id), prompt, working_dir, continue_conversation):
            chunk_buffer += chunk
            current_time = asyncio.get_event_loop().time()
            should_update = (
                current_time - last_update_time >= CHUNK_SEND_INTERVAL
                or len(chunk_buffer) >= 1000
            )
            if should_update and chunk_buffer:
                full_output += chunk_buffer
                chunk_buffer = ""
                last_update_time = current_time
                display_text = full_output
                if len(display_text) > MAX_MESSAGE_LENGTH:
                    display_text = "..." + display_text[-(MAX_MESSAGE_LENGTH - 3):]
                try:
                    await response_message.edit_text(display_text)
                except Exception as e:
                    logger.debug(f"Could not update message: {e}")

        if chunk_buffer:
            full_output += chunk_buffer

        if not full_output:
            full_output = "_No output from Claude._"
        else:
            session["has_conversation"] = True

        if len(full_output) <= MAX_MESSAGE_LENGTH:
            try:
                await response_message.edit_text(full_output)
            except Exception:
                pass
        else:
            try:
                await response_message.delete()
            except Exception:
                pass
            chunks = []
            remaining = full_output
            while remaining:
                if len(remaining) <= MAX_MESSAGE_LENGTH:
                    chunks.append(remaining)
                    break
                split_at = MAX_MESSAGE_LENGTH
                for sep in ["\n", " "]:
                    last_sep = remaining[:MAX_MESSAGE_LENGTH].rfind(sep)
                    if last_sep > MAX_MESSAGE_LENGTH // 2:
                        split_at = last_sep + 1
                        break
                chunks.append(remaining[:split_at])
                remaining = remaining[split_at:]
            for i, chunk in enumerate(chunks):
                prefix = f"*[Part {i + 1}/{len(chunks)}]*\n" if len(chunks) > 1 else ""
                await update.message.reply_text(
                    prefix + chunk,
                    parse_mode=ParseMode.MARKDOWN if prefix else None,
                )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle photo messages - download to current project folder."""
    if not is_authorized(update.effective_chat.id):
        await unauthorized_response(update)
        return

    # Telegram sends multiple sizes; use the largest
    photo = update.message.photo[-1]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"photo_{timestamp}.jpg"
    await _download_and_notify(update, context, photo.file_id, filename)


async def handle_document_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle image documents (sent as files) - download preserving original filename."""
    if not is_authorized(update.effective_chat.id):
        await unauthorized_response(update)
        return

    doc = update.message.document
    filename = doc.file_name or f"image_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    await _download_and_notify(update, context, doc.file_id, filename)


def main() -> None:
    """Start the bot."""
    if not BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not set.")
        print("Run 'claude-gateway setup' to configure the bot.")
        return

    if not ALLOWED_CHAT_IDS:
        print("Warning: ALLOWED_CHAT_IDS not set - no users will be authorized.")
        print("Run the bot and send a message to get your chat ID, then run 'claude-gateway setup'.")

    # Create application
    application = Application.builder().token(BOT_TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("project", project_command))
    application.add_handler(CommandHandler("newproject", newproject_command))
    application.add_handler(CallbackQueryHandler(project_callback, pattern=r"^project:"))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("new", new_command))
    application.add_handler(CommandHandler("stop", stop_command))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(
        MessageHandler(filters.Document.IMAGE, handle_document_image)
    )

    # Start bot
    logger.info("Starting Claude Gateway bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
