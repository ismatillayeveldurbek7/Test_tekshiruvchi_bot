from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.fsm.context import FSMContext
from config import ADMIN_IDS
from keyboards.inline_kb import get_admin_keyboard, get_back_keyboard
from states.bot_states import OMRStates
import database.db_helper as db
import csv
import io

admin_router = Router()


def is_admin_filter(msg_or_call):
    return msg_or_call.from_user.id in ADMIN_IDS


@admin_router.callback_query(F.data == "admin_panel")
async def process_admin_panel(call: CallbackQuery):
    await call.answer()
    if not is_admin_filter(call):
        await call.answer("Sizda admin huquqi yo‘q.", show_alert=True)
        return
    await call.message.answer(
        "⚙️ *ADMIN PANEL*\n\nBu yerda test kalitlari va natijalar boshqariladi.",
        parse_mode="Markdown",
        reply_markup=get_admin_keyboard(),
    )


@admin_router.callback_query(F.data == "admin_set_keys")
async def setup_exam_keys(call: CallbackQuery, state: FSMContext):
    await call.answer()
    if not is_admin_filter(call):
        return
    await state.set_state(OMRStates.waiting_for_admin_keys)
    await call.message.answer(
        "🔑 *Yangi test kalitini kiriting*\n\n"
        "Format:\n"
        "`TEST_ID A,B,C,D,E,...`\n\n"
        "Masalan:\n"
        "`ONA_TILI_1 A,B,D,C,E,A,A,D,E,C`\n\n"
        "❗ Har bir savol uchun faqat A, B, C, D yoki E bo‘lsin. Savollar soni 35 ta bo‘lishi shart emas — nechta kalit kiritsangiz, shuncha savol tekshiriladi.",
        parse_mode="Markdown",
        reply_markup=get_back_keyboard(),
    )


@admin_router.message(OMRStates.waiting_for_admin_keys)
async def handle_key_config_text(msg: Message, state: FSMContext):
    if not is_admin_filter(msg):
        return
    if not msg.text:
        await msg.reply("❌ Matn yuboring. Format: `TEST_ID A,B,C,...`", parse_mode="Markdown")
        return

    parts = msg.text.strip().split(maxsplit=1)
    if len(parts) != 2:
        await msg.reply("❌ Format noto‘g‘ri. Masalan: `TEST1 A,B,C,D,E`", parse_mode="Markdown")
        return

    exam_id, raw_keys = parts[0].upper(), parts[1].upper().replace(" ", "")
    keys_list = [k.strip() for k in raw_keys.split(",") if k.strip()]
    valid_options = {"A", "B", "C", "D", "E"}

    if not keys_list:
        await msg.reply("❌ Kalitlar topilmadi.")
        return

    for idx, k in enumerate(keys_list, start=1):
        if k not in valid_options:
            await msg.reply(f"❌ {idx}-savol kaliti noto‘g‘ri: `{k}`. Faqat A, B, C, D, E bo‘ladi.", parse_mode="Markdown")
            return

    serialized_str = ",".join([f"{i}:{v}" for i, v in enumerate(keys_list, start=1)])
    db.save_answer_key(exam_id, serialized_str, msg.from_user.id)
    await state.clear()
    await msg.reply(
        f"✅ *Test kaliti saqlandi!*\n\n"
        f"🆔 Test ID: `{exam_id}`\n"
        f"🔢 Savollar soni: {len(keys_list)} ta\n\n"
        f"Endi foydalanuvchilar shu test bo‘yicha varaqani yuborib tekshirishi mumkin.",
        parse_mode="Markdown",
        reply_markup=get_back_keyboard(),
    )


@admin_router.callback_query(F.data == "admin_list_exams")
async def list_exams_database(call: CallbackQuery):
    await call.answer()
    if not is_admin_filter(call):
        return
    exams = db.get_all_exams()
    if not exams:
        await call.message.answer("ℹ️ Hali test kaliti kiritilmagan.", reply_markup=get_back_keyboard())
        return
    text = "📜 *MAVJUD TESTLAR:*\n\n"
    for exam_id, created_at in exams:
        key = db.get_answer_key(exam_id) or ""
        text += f"• `{exam_id}` — {len(key.split(',')) if key else 0} ta savol — {created_at}\n"
    await call.message.answer(text, parse_mode="Markdown", reply_markup=get_back_keyboard())


@admin_router.callback_query(F.data == "admin_export_results")
async def export_results(call: CallbackQuery, bot: Bot):
    await call.answer()
    if not is_admin_filter(call):
        return
    rows = db.get_all_results()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "User ID", "F.I.Sh", "Username", "Test ID", "To‘g‘ri", "Xato", "Bo‘sh", "Bir nechta", "Ball", "Foiz", "Javoblar", "Sana"])
    for r in rows:
        writer.writerow(r)
    file = BufferedInputFile(output.getvalue().encode("utf-8-sig"), filename="natijalar.csv")
    await bot.send_document(call.message.chat.id, file, caption="📥 Natijalar CSV fayli")
