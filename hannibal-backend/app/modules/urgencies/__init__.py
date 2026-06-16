"""Urgent-appointment handling (doctor-in-the-loop overbooking).

A patient signals an urgency -> the bot asks the doctor for approval via
WhatsApp -> only on approval is the (possibly overbooked) appointment booked.
A Celery timeout falls back to offering the patient a normal slot.
"""
