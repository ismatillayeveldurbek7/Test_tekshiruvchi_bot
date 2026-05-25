from aiogram.fsm.state import State, StatesGroup

class OMRStates(StatesGroup):
    waiting_for_admin_keys = State()  # State for submitting exam key string: EXAM_NAME A,B,C...
    waiting_for_omr_sheet = State()  # State to scan a sheet, prompting target user
    waiting_for_exam_selection = State()
