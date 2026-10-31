from enum import StrEnum


class EmailTemplate(StrEnum):
    LOGIN_CODE = "auth.login_code"
    REGISTER_CODE = "auth.register_code"
    EMAIL_CHANGE_CURRENT_CODE = "auth.email_change_current_code"
    EMAIL_CHANGE_NEW_CODE = "auth.email_change_new_code"
    EMAIL_CHANGED = "auth.email_changed"
