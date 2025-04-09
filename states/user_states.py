from aiogram.fsm.state import State, StatesGroup

class NatalInput(StatesGroup):
    waiting_for_year = State(); waiting_for_month = State(); waiting_for_day = State()
    waiting_for_hour = State(); waiting_for_minute = State(); waiting_for_city = State()
    waiting_for_partner_year = State(); waiting_for_partner_month = State(); waiting_for_partner_day = State()
    waiting_for_partner_hour = State(); waiting_for_partner_minute = State(); waiting_for_partner_city = State()

class DreamInput(StatesGroup): waiting_for_dream_text = State()
class SignsInput(StatesGroup): waiting_for_sign_text = State()
class PalmistryInput(StatesGroup): waiting_for_left_hand = State(); waiting_for_right_hand = State()
class HoroscopeTimeInput(StatesGroup): waiting_for_time = State()
class TermsAgreement(StatesGroup): waiting_for_agreement = State()

class AdminActions(StatesGroup):
    waiting_for_user_query_info = State()
    waiting_for_user_query_credits = State(); waiting_for_credits_amount = State(); waiting_for_reason_credits = State(); waiting_for_confirmation_credits = State()
    waiting_for_user_query_logs = State()
    waiting_for_payment_id_check = State()
    waiting_for_broadcast_message = State(); waiting_for_broadcast_confirmation = State()