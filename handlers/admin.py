import re
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from config import ADMIN_IDS
from keyboards.inline_kb import get_admin_keyboard, get_back_keyboard
from states.bot_states import OMRStates
import database.db_helper as db

admin_router = Router()
VALID_OPTIONS = {"A", "B", "C", "D", "E"}


def is_admin(obj) -> bool:
    return obj.from_user and obj.from_user.id in ADMIN_IDS


def parse_answer_key(text: str):
    text = (text or "").strip().upper()
    parts = text.split(maxsplit=1)
    if len(parts) != 2:
        raise ValueError("Format noto‘g‘ri. Masalan: TEST1 ABCDABCD")
    exam_id, raw = parts[0], parts[1].strip()
    # 1-A 2-B yoki 1:A,2:B formatlari
    pairs = re.findall(r"(\d+)\s*[-:.]\s*([ABCDE])", raw)
    if pairs:
        data = {int(n): a for n, a in pairs}
        if not data:
            raise ValueError("Javob kaliti topilmadi.")
        max_q = max(data)
        keys = []
        for i in range(1, max_q + 1):
            if i not in data:
                raise ValueError(f"{i}-savol javobi yo‘q.")
            keys.append(data[i])
        return exam_id, keys
    # ABCDABCD yoki A,B,C,D formatlari
    letters = re.findall(r"[ABCDE]", raw)
    if not letters:
        raise ValueError("Javoblar A/B/C/D/E ko‘rinishida bo‘lishi kerak.")
    return exam_id, letters


@admin_router.callback_query(F.data == "admin_panel")
async def process_admin_panel(call: CallbackQuery):
    if not is_admin(call):
        await call.answer("Bu bo‘lim faqat admin uchun.", show_alert=True)
        return
    await call.message.edit_text(
        "⚙️ *Admin panel*\n\nBu yerda test javob kalitlarini kiritasiz va mavjud testlarni ko‘rasiz.",
        parse_mode="Markdown",
        reply_markup=get_admin_keyboard(),
    )


@admin_router.callback_query(F.data == "admin_set_keys")
async def setup_exam_keys(call: CallbackQuery, state: FSMContext):
    if not is_admin(call):
        await call.answer("Bu bo‘lim faqat admin uchun.", show_alert=True)
        return
    await state.set_state(OMRStates.waiting_for_admin_keys)
    await call.message.edit_text(
        "🔑 *Javob kalitini yuboring*\n\n"
        "Quyidagi formatlardan biri bo‘ladi:\n"
        "`TEST1 ABCDABCDAB`\n"
        "yoki `TEST1 A,B,C,D,A,B`\n"
        "yoki `TEST1 1-A 2-B 3-C 4-D`\n\n"
        "Bitta xabarda test kodi va javoblarni yuboring.",
        parse_mode="Markdown",
        reply_markup=get_back_keyboard(),
    )


@admin_router.message(OMRStates.waiting_for_admin_keys)
async def handle_key_config_text(msg: Message, state: FSMContext):
    if not is_admin(msg):
        return
    try:
        exam_id, keys = parse_answer_key(msg.text)
    except ValueError as e:
        await msg.reply(f"❌ {e}", reply_markup=get_back_keyboard())
        return

    serialized = ",".join(f"{i+1}:{ans}" for i, ans in enumerate(keys))
    db.save_answer_key(exam_id, serialized, msg.from_user.id)
    await state.clear()
    await msg.reply(
        f"✅ *Javob kaliti saqlandi!*\n\n"
        f"Test kodi: `{exam_id}`\n"
        f"Savollar soni: *{len(keys)} ta*\n\n"
        "Endi foydalanuvchi shu test kodini tanlab varaqani yuborishi mumkin.",
        parse_mode="Markdown",
        reply_markup=get_back_keyboard(),
    )


@admin_router.callback_query(F.data == "admin_list_exams")
async def list_exams_database(call: CallbackQuery):
    if not is_admin(call):
        await call.answer("Bu bo‘lim faqat admin uchun.", show_alert=True)
        return
    exams = db.get_all_exams()
    if not exams:
        await call.message.edit_text("Hali test javob kaliti kiritilmagan.", reply_markup=get_back_keyboard())
        return
    text = "📜 *Mavjud testlar:*\n\n"
    for code, created in exams:
        key = db.get_answer_key(code) or ""
        count = len([x for x in key.split(",") if x.strip()])
        text += f"• `{code}` — {count} ta savol — {created}\n"
    await call.message.edit_text(text, parse_mode="Markdown", reply_markup=get_back_keyboard())
