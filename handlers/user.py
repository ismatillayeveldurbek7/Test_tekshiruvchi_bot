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


def _parse_keys(keys_str: str) -> dict:
    result = {}
    for item in keys_str.split(","):
        if ":" not in item:
            continue
        q, ans = item.split(":", 1)
        result[q.strip()] = ans.strip().upper()
    return result


async def send_main_menu(message, user_id: int):
    is_admin = user_id in ADMIN_IDS
    await message.answer(
        "🏠 *Asosiy menyu*\n\nKerakli bo‘limni tanlang:",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(is_admin),
    )


@user_router.message(Command("start"))
async def cmd_start(msg: Message):
    db.add_user(msg.from_user.id, msg.from_user.username or "", msg.from_user.full_name or "")
    await msg.reply(
        "👋 *Test tekshiruvchi botga xush kelibsiz!*\n\n"
        "Bu bot test varaqasidagi javoblarni kalit bilan solishtirib beradi.\n\n"
        "📌 Admin avval test kalitini kiritadi.\n"
        "📷 Keyin foydalanuvchi test varaqasi rasmini yuboradi.\n"
        "✅ Bot to‘g‘ri, xato, bo‘sh va bir nechta belgilangan javoblarni hisoblaydi.",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(msg.from_user.id in ADMIN_IDS),
    )


@user_router.callback_query(F.data == "back_to_main")
async def back_to_main_menu(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await state.clear()
    await send_main_menu(call.message, call.from_user.id)


@user_router.callback_query(F.data == "start_scanning")
async def prompt_exam_selection(call: CallbackQuery, state: FSMContext):
    await call.answer()
    exams = db.get_all_exams()
    if not exams:
        await call.message.answer("⚠️ Hali test kaliti kiritilmagan. Admin panel orqali kalit kiriting.", reply_markup=get_back_keyboard())
        return
    await state.set_state(OMRStates.waiting_for_exam_selection)
    text = "📝 *1-qadam: Test ID ni tanlang*\n\n"
    for row in exams:
        text += f"• `{row[0]}`\n"
    text += "\n👉 Yuqoridagi Test ID ni yozib yuboring:"
    await call.message.answer(text, parse_mode="Markdown", reply_markup=get_back_keyboard())


@user_router.message(OMRStates.waiting_for_exam_selection)
async def save_targeted_exam(msg: Message, state: FSMContext):
    if not msg.text:
        await msg.reply("❌ Test ID ni matn ko‘rinishida yuboring.")
        return
    exam_id = msg.text.strip().upper()
    keys_str = db.get_answer_key(exam_id)
    if not keys_str:
        await msg.reply(f"❌ `{exam_id}` topilmadi. Test ID ni qayta tekshirib yuboring:", parse_mode="Markdown")
        return
    await state.update_data(current_exam_id=exam_id)
    await state.set_state(OMRStates.waiting_for_omr_sheet)
    await msg.reply(
        f"🎯 Test tanlandi: `{exam_id}`\n\n"
        f"📷 Endi test varaqasining aniq rasmini yuboring.\n\n"
        f"Maslahatlar:\n"
        f"• Rasm tiniq bo‘lsin\n"
        f"• Varaqaning hamma chetlari ko‘rinsin\n"
        f"• Soya va qiyshayishni kamaytiring\n"
        f"• Bitta savolda 2 ta variant belgilansa, u savol xato/bekor deb olinadi",
        parse_mode="Markdown",
        reply_markup=get_back_keyboard(),
    )


@user_router.message(OMRStates.waiting_for_omr_sheet, F.photo)
async def process_omr_uploaded_photo(msg: Message, state: FSMContext, bot: Bot):
    user_data = await state.get_data()
    exam_id = user_data.get("current_exam_id")
    keys_str = db.get_answer_key(exam_id)
    if not keys_str:
        await msg.reply("❌ Test kaliti topilmadi. Qaytadan boshlang.", reply_markup=get_back_keyboard())
        await state.clear()
        return
    answer_keys_dict = _parse_keys(keys_str)
    await msg.reply("⏳ Rasm tekshirilmoqda... Iltimos kuting.")
    try:
        photo = msg.photo[-1]
        file_info = await bot.get_file(photo.file_id)
        raw_file = await bot.download_file(file_info.file_path)
        image_bytes = raw_file.read()
        evaluation = OMRProcessor.analyze_sheet(image_bytes, answer_keys_dict)

        total_q = evaluation["total_questions"]
        text_r = "📊 *TEKSHIRUV NATIJASI*\n\n"
        text_r += f"🆔 Test ID: `{exam_id}`\n"
        text_r += f"👤 Foydalanuvchi: {msg.from_user.full_name}\n\n"
        text_r += f"✅ To‘g‘ri javoblar: *{evaluation['correct_count']}/{total_q}*\n"
        text_r += f"❌ Xato javoblar: *{evaluation['wrong_count']}*\n"
        text_r += f"⚪ Bo‘sh qoldirilgan: *{evaluation['skipped_count']}*\n"
        text_r += f"⚠️ Bir nechta belgilangan: *{evaluation['invalid_count']}*\n\n"
        text_r += f"⭐ Ball: *{evaluation['total_score']}*\n"
        text_r += f"📈 Foiz: *{evaluation['percentage']}%*\n\n"

        details = []
        for q in evaluation["questions"]:
            if q["status"] != "correct":
                uz_status = {"wrong": "xato", "skipped": "bo‘sh", "invalid": "bir nechta"}.get(q["status"], q["status"])
                details.append(f"{q['num']}) siz: {q['student']} | kalit: {q['key']} | {uz_status}")
        if details:
            text_r += "🔎 *Xato/bo‘sh savollar:*\n" + "\n".join(details[:60])

        db.save_result(
            user_id=msg.from_user.id,
            exam_id=exam_id,
            correct=evaluation["correct_count"],
            wrong=evaluation["wrong_count"],
            skipped=evaluation["skipped_count"],
            invalid=evaluation["invalid_count"],
            total_score=evaluation["total_score"],
            pct=evaluation["percentage"],
            detected=",".join([f"{q['num']}:{q['student']}" for q in evaluation["questions"]]),
        )
        vis_image = BufferedInputFile(evaluation["visual_png"], filename="tekshirilgan_varaq.png")
        await bot.send_photo(msg.chat.id, vis_image, caption=text_r, parse_mode="Markdown", reply_markup=get_back_keyboard())
        await state.clear()
    except Exception as e:
        await msg.reply(f"❌ Rasmni tekshirishda xato: {e}\n\nRasm tiniq va to‘liq tushgan bo‘lishi kerak.", reply_markup=get_back_keyboard())


@user_router.message(OMRStates.waiting_for_omr_sheet)
async def wrong_file_type(msg: Message):
    await msg.reply("📷 Iltimos, test varaqasini rasm sifatida yuboring.", reply_markup=get_back_keyboard())


@user_router.callback_query(F.data == "my_history")
async def show_history(call: CallbackQuery):
    await call.answer()
    rows = db.get_user_history(call.from_user.id)
    if not rows:
        await call.message.answer("📭 Hali hech qanday test tekshirmagansiz.", reply_markup=get_back_keyboard())
        return
    text = "📊 *MENING NATIJALARIM:*\n\n"
    for r in rows:
        text += f"• `{r[0]}` — {r[1]} ta to‘g‘ri | {r[2]} ball | {r[3]}% | {r[4][:16]}\n"
    await call.message.answer(text, parse_mode="Markdown", reply_markup=get_back_keyboard())


@user_router.callback_query(F.data == "view_leaderboard")
async def prompt_leaderboard_exams(call: CallbackQuery):
    await call.answer()
    exams = db.get_all_exams()
    if not exams:
        await call.message.answer("⚠️ Hali test kaliti kiritilmagan.", reply_markup=get_back_keyboard())
        return
    buttons = [[InlineKeyboardButton(text=f"📊 {exam[0]}", callback_data=f"leaderboard_view:{exam[0]}")] for exam in exams]
    buttons.append([InlineKeyboardButton(text="🔙 Asosiy menyu", callback_data="back_to_main")])
    await call.message.answer("🏆 Qaysi test bo‘yicha TOP reytingni ko‘rasiz?", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@user_router.callback_query(F.data.startswith("leaderboard_view:"))
async def display_leaderboard_ranking(call: CallbackQuery):
    await call.answer()
    exam_id = call.data.split(":", 1)[1]
    rows = db.get_leaderboard(exam_id)
    if not rows:
        await call.message.answer(f"🏆 `{exam_id}` bo‘yicha hali natija yo‘q.", parse_mode="Markdown", reply_markup=get_back_keyboard())
        return
    text = f"🏆 *TOP 10: {exam_id}*\n\n"
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    for idx, r in enumerate(rows):
        text += f"{medals[idx]} {r[0]} — {r[1]} ball ({r[2]}%) | {r[3][:16]}\n"
    await call.message.answer(text, parse_mode="Markdown", reply_markup=get_back_keyboard())


@user_router.callback_query(F.data == "tutorial_info")
async def display_info_help(call: CallbackQuery):
    await call.answer()
    text = (
        "ℹ️ *Yo‘riqnoma*\n\n"
        "1️⃣ Admin paneldan test kalitini kiriting.\n"
        "2️⃣ Foydalanuvchi ‘Test varaqasini tekshirish’ tugmasini bosadi.\n"
        "3️⃣ Test ID ni tanlaydi.\n"
        "4️⃣ Varaqaning tiniq rasmini yuboradi.\n\n"
        "⚠️ Agar bitta savolda 2 yoki undan ko‘p variant belgilansa, u savol bekor/xato hisoblanadi."
    )
    await call.message.answer(text, parse_mode="Markdown", reply_markup=get_tutorial_keyboard())
