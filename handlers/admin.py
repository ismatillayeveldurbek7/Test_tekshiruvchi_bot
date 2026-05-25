from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from config import ADMIN_IDS
from keyboards.inline_kb import get_admin_keyboard, get_back_keyboard
from states.bot_states import OMRStates
import database.db_helper as db

admin_router = Router()


def is_admin_filter(msg_or_call):
    return msg_or_call.from_user.id in ADMIN_IDS


@admin_router.callback_query(F.data == "admin_panel")
async def process_admin_panel(call: CallbackQuery):
    if not is_admin_filter(call):
        await call.answer("Siz admin emassiz.", show_alert=True)
        return
    await call.message.edit_text(
        "⚙️ *Admin panel*\n\nBu yerda javob kalitlarini kiritasiz.",
        parse_mode="Markdown",
        reply_markup=get_admin_keyboard()
    )


@admin_router.callback_query(F.data == "admin_set_keys")
async def setup_exam_keys(call: CallbackQuery, state: FSMContext):
    if not is_admin_filter(call):
        return
    await state.set_state(OMRStates.waiting_for_admin_keys)
    await call.message.edit_text(
        "🔑 *Javob kalitini kiriting*\n\n"
        "Format:\n"
        "`TEST1 A,B,C,D,A,...`\n\n"
        "Jami 35 ta javob bo'lishi kerak.\n"
        "1–32-savollar: A/B/C/D\n"
        "33–35-savollar: A/B/C/D/E/F\n\n"
        "Masalan:\n"
        "`TEST1 A,B,C,D,A,C,B,D,A,B,C,D,A,B,C,D,B,A,C,D,B,A,C,D,A,B,C,D,B,C,D,A,E,D,F`",
        parse_mode="Markdown",
        reply_markup=get_back_keyboard()
    )


@admin_router.message(OMRStates.waiting_for_admin_keys)
async def handle_key_config_text(msg: Message, state: FSMContext):
    if not is_admin_filter(msg):
        return

    parts = msg.text.strip().split(maxsplit=1)
    if len(parts) != 2:
        await msg.reply("❌ Format noto'g'ri. Masalan: `TEST1 A,B,C,D,...`", parse_mode="Markdown")
        return

    exam_id = parts[0].upper().strip()
    keys_list = [k.strip().upper() for k in parts[1].replace("\n", ",").split(",") if k.strip()]

    if len(keys_list) != 35:
        await msg.reply(f"❌ 35 ta javob kerak. Siz {len(keys_list)} ta kiritdingiz.")
        return

    for idx, k in enumerate(keys_list, start=1):
        valid = {"A", "B", "C", "D"} if idx <= 32 else {"A", "B", "C", "D", "E", "F"}
        if k not in valid:
            await msg.reply(f"❌ {idx}-savolda '{k}' noto'g'ri. Ruxsat etilgan: {', '.join(sorted(valid))}")
            return

    serialized_str = ",".join([f"{i}:{v}" for i, v in enumerate(keys_list, start=1)])
    db.save_answer_key(exam_id, serialized_str, msg.from_user.id)
    await state.clear()

    await msg.reply(
        f"✅ *Javob kaliti saqlandi!*\n\n"
        f"Test kodi: `{exam_id}`\n"
        f"Savollar soni: 35 ta\n\n"
        f"Endi foydalanuvchilar shu test kodi orqali varaqani tekshirishi mumkin.",
        parse_mode="Markdown",
        reply_markup=get_back_keyboard()
    )


@admin_router.callback_query(F.data == "admin_list_exams")
async def list_exams_database(call: CallbackQuery):
    if not is_admin_filter(call):
        return
    exams = db.get_all_exams()
    if not exams:
        await call.message.edit_text("ℹ️ Hali javob kaliti kiritilmagan.", reply_markup=get_back_keyboard())
        return

    text = "📜 *Kiritilgan test kalitlari:*\n\n"
    for row in exams:
        text += f"• `{row[0]}` — {row[1]}\n"
    await call.message.edit_text(text, parse_mode="Markdown", reply_markup=get_back_keyboard())
