from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from keyboards.inline_kb import get_main_keyboard, get_back_keyboard, get_tutorial_keyboard
from states.bot_states import OMRStates
from omr_engine.omr_processor import OMRProcessor
from config import ADMIN_IDS
import database.db_helper as db

user_router = Router()


def _parse_keys(keys_str: str):
    answer_keys_dict = {}
    for item in keys_str.split(","):
        if ":" not in item:
            continue
        q, ans = item.split(":", 1)
        answer_keys_dict[q.strip()] = ans.strip().upper()
    return answer_keys_dict


@user_router.message(Command("start"))
async def cmd_start(msg: Message, state: FSMContext):
    await state.clear()
    db.add_user(msg.from_user.id, msg.from_user.username or "", msg.from_user.full_name or "")
    is_admin = msg.from_user.id in ADMIN_IDS
    await msg.answer(
        "👋 *Test tekshiruvchi botga xush kelibsiz!*\n\n"
        "Bu bot Akbarali Boymirzayev namunasi bo'yicha 35 ta savollik javob varaqasini OpenCV orqali tekshiradi.\n\n"
        "1–32-savollar: A/B/C/D\n"
        "33–35-savollar: A/B/C/D/E/F\n\n"
        "Boshlash uchun pastdagi tugmani bosing.",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(is_admin)
    )


@user_router.callback_query(F.data == "back_to_main")
async def back_to_main_menu(call: CallbackQuery, state: FSMContext):
    await state.clear()
    is_admin = call.from_user.id in ADMIN_IDS
    await call.message.edit_text(
        "🏠 *Asosiy menyu*\n\nKerakli bo'limni tanlang:",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(is_admin)
    )


@user_router.callback_query(F.data == "start_scanning")
async def prompt_exam_selection(call: CallbackQuery, state: FSMContext):
    exams = db.get_all_exams()
    if not exams:
        await call.message.edit_text(
            "⚠️ Hali javob kaliti kiritilmagan. Admin avval test kalitini kiritsin.",
            reply_markup=get_back_keyboard()
        )
        return

    await state.set_state(OMRStates.waiting_for_exam_selection)
    text = "📝 *1-qadam: Test kodini yuboring*\n\nMavjud test kodlari:\n"
    for row in exams:
        text += f"• `{row[0]}`\n"
    text += "\nMasalan: `TEST1`"
    await call.message.edit_text(text, parse_mode="Markdown", reply_markup=get_back_keyboard())


@user_router.message(OMRStates.waiting_for_exam_selection)
async def save_targeted_exam(msg: Message, state: FSMContext):
    exam_id = msg.text.strip().upper()
    keys_str = db.get_answer_key(exam_id)
    if not keys_str:
        await msg.reply(f"❌ `{exam_id}` topilmadi. Yuqoridagi kodlardan birini aniq yuboring.", parse_mode="Markdown")
        return

    await state.update_data(current_exam_id=exam_id)
    await state.set_state(OMRStates.waiting_for_omr_sheet)
    await msg.reply(
        f"✅ Test kodi tanlandi: `{exam_id}`\n\n"
        "📷 Endi to'ldirilgan javob varaqasi rasmini yuboring.\n\n"
        "Muhim:\n"
        "• rasmda varaq to'liq ko'rinsin\n"
        "• kamera iloji boricha tik bo'lsin\n"
        "• soyalar kam bo'lsin\n"
        "• 1-savolda 2 ta variant belgilansa, avtomatik xato hisoblanadi",
        parse_mode="Markdown",
        reply_markup=get_back_keyboard()
    )


@user_router.message(OMRStates.waiting_for_omr_sheet, F.photo)
async def process_omr_uploaded_photo(msg: Message, state: FSMContext, bot: Bot):
    user_data = await state.get_data()
    exam_id = user_data.get("current_exam_id")
    keys_str = db.get_answer_key(exam_id)
    if not keys_str:
        await msg.reply("❌ Test kodi topilmadi. Qaytadan boshlang.", reply_markup=get_back_keyboard())
        return

    answer_keys_dict = _parse_keys(keys_str)
    await msg.reply("⏳ Rasm tekshirilyapti... Iltimos, kuting.")

    photo = msg.photo[-1]
    file_info = await bot.get_file(photo.file_id)
    raw_file = await bot.download_file(file_info.file_path)
    image_bytes = raw_file.read()

    try:
        evaluation = OMRProcessor.analyze_sheet(image_bytes, answer_keys_dict)

        text_r = (
            f"📊 *Tekshiruv natijasi*\n\n"
            f"🔑 Test kodi: `{exam_id}`\n"
            f"👤 O'quvchi: {msg.from_user.full_name}\n\n"
            f"✅ To'g'ri: {evaluation['correct_count']}/35\n"
            f"❌ Xato: {evaluation['wrong_count']}\n"
            f"⚪ Bo'sh: {evaluation['skipped_count']}\n"
            f"⚠️ 2 ta belgilangan: {evaluation['invalid_count']}\n"
            f"📈 Foiz: {evaluation['percentage']}%\n"
            f"🧭 Align: `{evaluation.get('align_method', '-')}`\n\n"
        )

        bad = [q for q in evaluation['questions'] if q['status'] != 'correct']
        if bad:
            text_r += "*Xato/bo'sh savollar:*\n"
            for q in bad[:35]:
                status_txt = {
                    "wrong": "xato",
                    "skipped": "bo'sh",
                    "invalid": "2 ta belgi"
                }.get(q['status'], q['status'])
                text_r += f"{q['num']}) javob: {q['student']} | kalit: {q['key']} | {status_txt}\n"

        db.save_result(
            user_id=msg.from_user.id,
            exam_id=exam_id,
            correct=evaluation['correct_count'],
            wrong=evaluation['wrong_count'],
            skipped=evaluation['skipped_count'],
            invalid=evaluation['invalid_count'],
            total_score=evaluation['total_score'],
            pct=evaluation['percentage'],
            detected=",".join([f"{q['num']}:{q['student']}" for q in evaluation['questions']])
        )

        vis_image = BufferedInputFile(evaluation['visual_png'], filename="tekshirilgan_natija.png")
        await bot.send_photo(
            chat_id=msg.chat.id,
            photo=vis_image,
            caption=text_r[:1024],
            parse_mode="Markdown",
            reply_markup=get_back_keyboard()
        )
        if len(text_r) > 1024:
            await msg.answer(text_r[1024:], parse_mode="Markdown", reply_markup=get_back_keyboard())
        await state.clear()

    except Exception as e:
        await msg.reply(
            f"❌ Tekshirishda xatolik bo'ldi: {e}\n\nRasmda varaq to'liq ko'rinishiga e'tibor bering.",
            reply_markup=get_back_keyboard()
        )


@user_router.message(OMRStates.waiting_for_omr_sheet)
async def process_non_photo(msg: Message):
    await msg.reply("📷 Iltimos, matn emas, javob varaqasi rasmini yuboring.", reply_markup=get_back_keyboard())


@user_router.callback_query(F.data == "my_history")
async def show_history(call: CallbackQuery):
    rows = db.get_user_history(call.from_user.id)
    if not rows:
        await call.message.edit_text("📭 Sizda hali natijalar yo'q.", reply_markup=get_back_keyboard())
        return

    text = "📊 *Mening oxirgi natijalarim:*\n\n"
    for r in rows:
        text += f"• `{r[0]}` — {r[1]}/35, {r[3]}% | {r[4][:16]}\n"
    await call.message.edit_text(text, parse_mode="Markdown", reply_markup=get_back_keyboard())


@user_router.callback_query(F.data == "view_leaderboard")
async def prompt_leaderboard_exams(call: CallbackQuery):
    exams = db.get_all_exams()
    if not exams:
        await call.message.edit_text("⚠️ Hali test kaliti yo'q.", reply_markup=get_back_keyboard())
        return

    buttons = []
    for exam in exams:
        buttons.append([InlineKeyboardButton(text=f"📊 {exam[0]}", callback_data=f"leaderboard_view:{exam[0]}")])
    buttons.append([InlineKeyboardButton(text="🔙 Asosiy menyu", callback_data="back_to_main")])
    await call.message.edit_text("🏆 Qaysi test reytingini ko'rmoqchisiz?", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@user_router.callback_query(F.data.startswith("leaderboard_view:"))
async def display_leaderboard_ranking(call: CallbackQuery):
    exam_id = call.data.split(":", 1)[1]
    rows = db.get_leaderboard(exam_id)
    if not rows:
        await call.message.edit_text(f"🏆 `{exam_id}` bo'yicha hali natija yo'q.", parse_mode="Markdown", reply_markup=get_back_keyboard())
        return

    text = f"🏆 *TOP 10: {exam_id}*\n\n"
    for idx, r in enumerate(rows, start=1):
        text += f"{idx}) {r[0]} — {r[1]}/35, {r[2]}%\n"
    await call.message.edit_text(text, parse_mode="Markdown", reply_markup=get_back_keyboard())


@user_router.callback_query(F.data == "tutorial_info")
async def display_info_help(call: CallbackQuery):
    text = (
        "ℹ️ *Qo'llanma*\n\n"
        "Bot faqat shu ko'rinishdagi blankani tekshiradi:\n"
        "• 1–32-savollar: A/B/C/D\n"
        "• 33–35-savollar: A/B/C/D/E/F\n\n"
        "Aniq tekshirish uchun rasmda butun varaq ko'rinsin, javoblar qora ruchka bilan bo'yalgan bo'lsin."
    )
    await call.message.edit_text(text, parse_mode="Markdown", reply_markup=get_tutorial_keyboard())
