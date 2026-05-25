from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from keyboards.inline_kb import get_main_keyboard, get_back_keyboard, get_tutorial_keyboard
from states.bot_states import OMRStates
from omr_engine.omr_processor import OMRProcessor
from config import ADMIN_IDS
import database.db_helper as db
import io
import requests

user_router = Router()

@user_router.message(Command("start"))
async def cmd_start(msg: Message):
    db.add_user(msg.from_user.id, msg.from_user.username or "Anonymous", msg.from_user.full_name)
    is_admin = msg.from_user.id in ADMIN_IDS
    await msg.reply(
        f"👋 *Welcome to the official OMR Test Checker Bot!*\n\n"
        f"This bot utilizes highly-accurate computer vision to instantly process OMR Answer Sheets "
        f"from photos taken with mobile cameras.\n\n"
        f"**Sheet Format**: Standard 35-questions card (A, B, C, D, E bubbles).\n\n"
        f"To submit a scan, click down below:",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(is_admin)
    )

@user_router.callback_query(F.data == "back_to_main")
async def back_to_main_menu(call: CallbackQuery, state: FSMContext):
    await state.clear()
    is_admin = call.from_user.id in ADMIN_IDS
    await call.message.edit_text(
        "🏠 *Main Dashboard Menu*\n\n"
        "Select an action:",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(is_admin)
    )

@user_router.callback_query(F.data == "start_scanning")
async def prompt_exam_selection(call: CallbackQuery, state: FSMContext):
    exams = db.get_all_exams()
    if not exams:
        await call.message.edit_text(
            "⚠️ No Exams registered! Currently admins have not set up test templates in database yet.",
            reply_markup=get_back_keyboard()
        )
        return
        
    await state.set_state(OMRStates.waiting_for_exam_selection)
    text = "📝 *Step 1: Write down/select targeted EXAM ID from registered database*\n\n"
    for row in exams:
        text += f"• Code: `{row[0]}`\n"
    text += "\n👉 Please TYPE and send the exact exam code from above (e.g. MATH101):"
    
    await call.message.edit_text(text, parse_mode="Markdown", reply_markup=get_back_keyboard())

@user_router.message(OMRStates.waiting_for_exam_selection)
async def save_targeted_exam(msg: Message, state: FSMContext):
    exam_id = msg.text.strip().upper()
    keys_str = db.get_answer_key(exam_id)
    
    if not keys_str:
        await msg.reply(f"❌ '{exam_id}' is not found. Check correct spelling and send again:")
        return
        
    await state.update_data(current_exam_id=exam_id)
    await state.set_state(OMRStates.waiting_for_omr_sheet)
    await msg.reply(
        f"🎯 **Exam ID Activated**: {exam_id}\n\n"
        f"📷 *Step 2: Take and Upload a clear photo of the filled OMR sheet*\n\n"
        f"**Photography Tips for best accuracy**:\n"
        f"• Place sheet on high-contrast flat backgrounds\n"
        f"• Minimize shadows and overhead flashes\n"
        f"• Capture the full 4 borders clearly for automatic perspective rectifications.",
        parse_mode="Markdown"
    )

@user_router.message(OMRStates.waiting_for_omr_sheet, F.photo)
async def process_omr_uploaded_photo(msg: Message, state: FSMContext, bot: Bot):
    user_data = await state.get_data()
    exam_id = user_data.get("current_exam_id")
    
    keys_str = db.get_answer_key(exam_id)
    # Parse answers keys: "1:A,2:B,3:C..." into dict
    answer_keys_dict = {}
    for item in keys_str.split(","):
        q, ans = item.split(":")
        answer_keys_dict[q] = ans
        
    await msg.reply("⚡ *Running computer vision engine scanning...* Checking grid markers and bubbles filled pixels density.", parse_mode="Markdown")
    
    # Download photo from telegram servers
    photo = msg.photo[-1] # Highest resolution
    file_info = await bot.get_file(photo.file_id)
    raw_file = await bot.download_file(file_info.file_path)
    image_bytes = raw_file.read()
    
    try:
        # Run calculation
        evaluation = OMRProcessor.analyze_sheet(image_bytes, answer_keys_dict)
        
        # Format textual results string
        text_r = f"📊 *OMR EVALUATION REPORT:*\n"
        text_r += f"🔑 **Exam Model ID**: `{exam_id}`\n"
        text_r += f"👤 **Student**: {msg.from_user.full_name}\n\n"
        text_r += f"✅ **Correct Answers**: {evaluation['correct_count']}/35\n"
        text_r += f"❌ **Wrong Selections**: {evaluation['wrong_count']}\n"
        text_r += f"⚪ **Skipped (Empty)**: {evaluation['skipped_count']}\n"
        text_r += f"⚠️ **Invalid Multi-marked**: {evaluation['invalid_count']}\n\n"
        text_r += f"⭐️ **Final Weighted Score**: {evaluation['total_score']} pts\n"
        text_r += f"📈 **Percentage Grade**: {evaluation['percentage']}%\n\n"
        
        # Check if there are warning invalid rules violation
        invalid_list = [q for q in evaluation['questions'] if q['status'] == 'invalid']
        if invalid_list:
            text_r += "🔬 *DETECTION WARNINGS:*\n"
            for inv in invalid_list:
                text_r += f"• **Question {inv['num']}**: Multiple bubble choices [*{inv['student']}*] filled simultaneously. Mark as invalid rule offense.\n"
            text_r += "\n"
            
        # Register history
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
        
        # Prepare processed image file payload
        vis_image = BufferedInputFile(evaluation['visual_png'], filename="omr_checked_rectified.png")
        
        await bot.send_photo(
            chat_id=msg.chat.id,
            photo=vis_image,
            caption=text_r,
            parse_mode="Markdown",
            reply_markup=get_back_keyboard()
        )
        await state.clear()
        
    except Exception as e:
        await msg.reply(f"❌ *Engine extraction error!* Make sure the uploaded sheet photo is neat and follows grid lines format. Logs: {str(e)}", parse_mode="Markdown")

@user_router.callback_query(F.data == "my_history")
async def show_history(call: CallbackQuery):
    rows = db.get_user_history(call.from_user.id)
    if not rows:
        await call.message.edit_text("📭 You haven't scanned any OMR sheets yet. Submit a test today!", reply_markup=get_back_keyboard())
        return
        
    text = "📊 *YOUR HISTORIC SCORES:*\n\n"
    for r in rows:
        text += f"• 🎯 **{r[0]}**: Score: {r[1]}/35 ({r[2]} pts) | **{r[3]}%** - {r[4][:10]}\n"
        
    await call.message.edit_text(text, parse_mode="Markdown", reply_markup=get_back_keyboard())

@user_router.callback_query(F.data == "view_leaderboard")
async def prompt_leaderboard_exams(call: CallbackQuery):
    exams = db.get_all_exams()
    if not exams:
        await call.message.edit_text("⚠️ No active exam templates compiled yet inside db.", reply_markup=get_back_keyboard())
        return
        
    text = "🏆 *View Leaderboard stats*\nChoose an Exam Code to inspect top performance rankings:\n\n"
    buttons = []
    for exam in exams:
        buttons.append([InlineKeyboardButton(text=f"📊 Rank: {exam[0]}", callback_data=f"leaderboard_view:{exam[0]}")])
    buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="back_to_main")])
    
    await call.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@user_router.callback_query(F.data.startswith("leaderboard_view:"))
async def display_leaderboard_ranking(call: CallbackQuery):
    exam_id = call.data.split(":")[1]
    rows = db.get_leaderboard(exam_id)
    
    if not rows:
        await call.message.edit_text(f"🏆 *Leaderboard: {exam_id}*\n\nNo submissions parsed yet for this exam.", parse_mode="Markdown", reply_markup=get_back_keyboard())
        return
        
    text = f"🏆 *TOP 10 SCORES: {exam_id}*\n\n"
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    for idx, r in enumerate(rows):
        medal = medals[idx] if idx < len(medals) else "👤"
        text += f"{medal} **{r[0]}** - {r[1]} pts ({r[2]}%) | {r[3][:16]}\n"
        
    await call.message.edit_text(text, parse_mode="Markdown", reply_markup=get_back_keyboard())

@user_router.callback_query(F.data == "tutorial_info")
async def display_info_help(call: CallbackQuery):
    text = (
        "📖 *How the Telegram OMR Engine Works*\n\n"
        "1️⃣ **Perspective Transformation**: Using four outer circles coordinates, the OpenCV library computes "
        "bilinear matrixes to rotate and flatten images of crumpled papers.\n\n"
        "2️⃣ **Otsu Binarization**: Converts high-res camera matrixes into binary layers, isolating shadows as simple background constants.\n\n"
        "3️⃣ **Grid Row Scanning**: Computes high-density black pixel counts within the standard option circle masks.\n\n"
        "4️⃣ **Double Detection Safehouse**: If multiple bubble zones are filled simultaneously for a single question grid, "
        "the bot triggers an invalid warning and flags with a bold custom red outline panel on output metrics PDF/PNG layers."
    )
    await call.message.edit_text(text, parse_mode="Markdown", reply_markup=get_tutorial_keyboard())
