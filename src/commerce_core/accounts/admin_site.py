"""The admin site: staff reach it only with a verified TOTP device (A6b)."""

from django_otp.admin import OTPAdminSite


class CoreAdminSite(OTPAdminSite):
    site_header = "Store administration"
    site_title = "Store administration"
    index_title = "Administration"
