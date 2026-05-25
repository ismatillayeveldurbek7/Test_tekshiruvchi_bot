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


def parse_key_string(keys_str: str):
    result = {}
    for item in (keys_str or "").split(","):
        if not item.strip() or ":" not in item:
            continue
        q, ans = item.split(":", 1)
        result[q.strip()] = ans.strip().upper()
    return result


async def show_main(message_or_call, state: FSMContext | None = None):
    if state:
        await state.clear()
    user = message_or_call.from_user
    is_admin = user.id in ADMIN_IDS
    text = (
        "🏠 *Asosiy menyu*\n\n"
        "Bu bot test varaqasidagi javoblarni tekshiradi.\n"
        "Avval admin javob kalitini kiritadi, keyin foydalanuvchi test varaqasi rasmini yuboradi."
    )
    if isinstance(message_or_call, CallbackQuery):
        await message_or_call.message.edit_text(text, parse_mode="Markdown", reply_markup=get_main_keyboard(is_admin))
        await message_or_call.answer()
    else:
        await message_or_call.answer(text, parse_mode="Markdown", reply_markup=get_main_keyboard(is_admin))


@user_router.message(Command("start"))
async def cmd_start(msg: Message, state: FSMContext):
    db.add_user(msg.from_user.id, msg.from_user.username or "", msg.from_user.full_name or "")
    await show_main(msg, state)


@user_router.callback_query(F.data == "back_to_main")
async def back_to_main_menu(call: CallbackQuery, state: FSMContext):
    await show_main(call, state)


@user_router.callback_query(F.data == "start_scanning")
async def prompt_exam_selection(call: CallbackQuery, state: FSMContext):
    exams = db.get_all_exams()
    if not exams:
        await call.message.edit_text(
            "⚠️ Hali javob kaliti kiritilmagan. Admin paneldan avval test kalitini kiriting.",
            reply_markup=get_back_keyboard(),
        )
        await call.answer()
        return
    await state.set_state(OMRStates.waiting_for_exam_selection)
    text = "📝 *Test kodini tanlang*\n\n"
    for code, _ in exams:
        text += f"• `{code}`\n"
    text += "\nYuqoridagi test kodini yozib yuboring. Masalan: `TEST1`"
    await call.message.edit_text(text, parse_mode="Markdown", reply_markup=get_back_keyboard())
    await call.answer()


@user_router.message(OMRStates.waiting_for_exam_selection)
async def save_targeted_exam(msg: Message, state: FSMContext):
    exam_id = (msg.text or "").strip().upper()
    keys_str = db.get_answer_key(exam_id)
    if not keys_str:
        await msg.reply("❌ Bunday test kodi topilmadi. Kodni to‘g‘ri yozib qayta yuboring.", reply_markup=get_back_keyboard())
        return
    await state.update_data(current_exam_id=exam_id)
    await state.set_state(OMRStates.waiting_for_omr_sheet)
    await msg.reply(
        f"✅ Test tanlandi: `{exam_id}`\n\n"
        "Endi test varaqasining *aniq va to‘liq* rasmini yuboring.\n\n"
        "Muhim: rasmda varaqaning 4 tomoni ko‘rinsin, soya kam bo‘lsin, javoblar doira/katak ichida aniq bo‘yalgan bo‘lsin.",
        parse_mode="Markdown",
        reply_markup=get_back_keyboard(),
    )


@user_router.message(OMRStates.waiting_for_omr_sheet, F.photo)
async def process_omr_uploaded_photo(msg: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    exam_id = data.get("current_exam_id")
    keys = parse_key_string(db.get_answer_key(exam_id))
    if not keys:
        await msg.reply("❌ Bu test uchun javob kaliti buzilgan yoki topilmadi.", reply_markup=get_back_keyboard())
        await state.clear()
        return

    wait_msg = await msg.reply("⏳ Rasm tekshirilmoqda...")
    photo = msg.photo[-1]
    file_info = await bot.get_file(photo.file_id)
    raw_file = await bot.download_file(file_info.file_path)
    image_bytes = raw_file.read()

    try:
        ev = OMRProcessor.analyze_sheet(image_bytes, keys)
    except Exception as e:
        await wait_msg.edit_text(
            "❌ Rasmni tekshirishda xato bo‘ldi.\n\n"
            "Sabab: rasm sifati yoki varaqa koordinatasi mos kelmasligi mumkin.\n"
            f"Texnik xabar: `{str(e)}`",
            parse_mode="Markdown",
            reply_markup=get_back_keyboard(),
        )
        return

    total = len(keys)
    text = (
        f"📊 *Test natijasi*\n\n"
        f"Test kodi: `{exam_id}`\n"
        f"O‘quvchi: *{msg.from_user.full_name}*\n\n"
        f"✅ To‘g‘ri: *{ev['correct_count']} / {total}*\n"
        f"❌ Xato: *{ev['wrong_count']}*\n"
        f"⚪ Bo‘sh: *{ev['skipped_count']}*\n"
        f"⚠️ Bitta savolda 2 ta belgi: *{ev['invalid_count']}*\n"
        f"📈 Foiz: *{ev['percentage']}%*\n\n"
    )
    wrong_items = [q for q in ev["questions"] if q["status"] != "correct"]
    if wrong_items:
        text += "*Xato/bo‘sh savollar:*\n"
        for q in wrong_items[:30]:
            text += f"{q['num']}) kalit: {q['key']} | belgilangan: {q['student']}\n"
        if len(wrong_items) > 30:
            text += f"... yana {len(wrong_items)-30} ta\n"

    db.save_result(
        user_id=msg.from_user.id,
        exam_id=exam_id,
        correct=ev["correct_count"],
        wrong=ev["wrong_count"],
        skipped=ev["skipped_count"],
        invalid=ev["invalid_count"],
        total_score=ev["total_score"],
        pct=ev["percentage"],
        detected=",".join(f"{q['num']}:{q['student']}" for q in ev["questions"]),
    )
    await state.clear()
    vis = BufferedInputFile(ev["visual_png"], filename="tekshirilgan_test.png")
    await bot.send_photo(msg.chat.id, vis, caption=text, parse_mode="Markdown", reply_markup=get_back_keyboard())
    try:
        await wait_msg.delete()
    except Exception:
        pass


@user_router.message(OMRStates.waiting_for_omr_sheet)
async def photo_required(msg: Message):
    await msg.reply("Iltimos, test varaqasini rasm ko‘rinishida yuboring.", reply_markup=get_back_keyboard())


@user_router.callback_query(F.data == "my_history")
async def show_history(call: CallbackQuery):
    rows = db.get_user_history(call.from_user.id)
    if not rows:
        await call.message.edit_text("📭 Sizda hali tekshirilgan testlar yo‘q.", reply_markup=get_back_keyboard())
        await call.answer()
        return
    text = "📊 *Mening oxirgi natijalarim:*\n\n"
    for exam_id, correct, total_score, pct, scanned_at in rows:
        text += f"• `{exam_id}` — {correct} ta to‘g‘ri — {pct}% — {scanned_at[:16]}\n"
    await call.message.edit_text(text, parse_mode="Markdown", reply_markup=get_back_keyboard())
    await call.answer()


@user_router.callback_query(F.data == "view_leaderboard")
async def prompt_leaderboard_exams(call: CallbackQuery):
    exams = db.get_all_exams()
    if not exams:
        await call.message.edit_text("Hali testlar mavjud emas.", reply_markup=get_back_keyboard())
        await call.answer()
        return
    buttons = [[InlineKeyboardButton(text=f"🏆 {code}", callback_data=f"leaderboard_view:{code}")] for code, _ in exams]
    buttons.append([InlineKeyboardButton(text="🔙 Asosiy menyu", callback_data="back_to_main")])
    await call.message.edit_text("Qaysi test reytingini ko‘rmoqchisiz?", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await call.answer()


@user_router.callback_query(F.data.startswith("leaderboard_view:"))
async def display_leaderboard_ranking(call: CallbackQuery):
    exam_id = call.data.split(":", 1)[1]
    rows = db.get_leaderboard(exam_id)
    if not rows:
        await call.message.edit_text(f"🏆 `{exam_id}` bo‘yicha hali natija yo‘q.", parse_mode="Markdown", reply_markup=get_back_keyboard())
        await call.answer()
        return
    text = f"🏆 *TOP 10 — {exam_id}*\n\n"
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    for i, r in enumerate(rows):
        text += f"{medals[i]} {r[0]} — {r[1]} ta — {r[2]}%\n"
    await call.message.edit_text(text, parse_mode="Markdown", reply_markup=get_back_keyboard())
    await call.answer()


@user_router.callback_query(F.data == "tutorial_info")
async def display_info_help(call: CallbackQuery):
    text = (
        "ℹ️ *Qo‘llanma*\n\n"
        "1. Admin panelga kiring.\n"
        "2. Javob kalitini kiriting: `TEST1 ABCDABCD`\n"
        "3. Foydalanuvchi `Test varaqasini tekshirish` tugmasini bosadi.\n"
        "4. Test kodini yozadi va rasm yuboradi.\n\n"
        "⚠️ Bitta savolda 2 ta variant belgilansa, bot uni xato deb hisoblaydi.\n"
        "⚠️ Eng yaxshi ishlashi uchun javob varaqasi formati doim bir xil bo‘lishi kerak."
    )
    await call.message.edit_text(text, parse_mode="Markdown", reply_markup=get_tutorial_keyboard())
    await call.answer()
