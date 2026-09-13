"""Curated catalogues offered during onboarding.

These lists are written by hand, on purpose. A doctor filling in a blank
textarea produces free text that is inconsistent between offices ("BBVA" in one,
"Bancomer" in the next) and incomplete under time pressure — so onboarding
suggests a vetted starting point per specialty and lets the doctor adjust it.

They are suggestions, never a closed set: every list is editable in the wizard
and every specialty falls back to `GENERAL_*` plus an "Otro" free-text escape.

Keep this module data-only — no IA generates these lists, and nothing here
should import from the modules that consume it.
"""

from __future__ import annotations

# --- Specialties -----------------------------------------------------------
# `id` is what gets stored in Office.specialty; `label` is what the doctor sees.
OTHER_SPECIALTY_ID = "otra"

SPECIALTIES: list[dict[str, str]] = [
    {"id": "oftalmologia", "label": "Oftalmología"},
    {"id": "medicina_general", "label": "Medicina general"},
    {"id": "pediatria", "label": "Pediatría"},
    {"id": "ginecologia", "label": "Ginecología y obstetricia"},
    {"id": "dermatologia", "label": "Dermatología"},
    {"id": "psicologia", "label": "Psicología"},
    {"id": "psiquiatria", "label": "Psiquiatría"},
    {"id": "nutricion", "label": "Nutrición"},
    {"id": "odontologia", "label": "Odontología"},
    {"id": "ortopedia", "label": "Ortopedia y traumatología"},
    {"id": "cardiologia", "label": "Cardiología"},
    {"id": "otorrinolaringologia", "label": "Otorrinolaringología"},
    {"id": "gastroenterologia", "label": "Gastroenterología"},
    {"id": "neurologia", "label": "Neurología"},
    {"id": "urologia", "label": "Urología"},
    {"id": "endocrinologia", "label": "Endocrinología"},
    {"id": OTHER_SPECIALTY_ID, "label": "Otra"},
]

# --- Services --------------------------------------------------------------
# Every specialty starts from these two; the catalogue adds what is typical.
GENERAL_SERVICES: list[str] = [
    "Primera consulta",
    "Consulta subsecuente",
]

# First shot is ophthalmology, to be validated with the real ophthalmologist
# before the demo. The rest are starting points, deliberately short.
SPECIALTY_SERVICES: dict[str, list[str]] = {
    "oftalmologia": [
        "Consulta oftalmológica general",
        "Examen de agudeza visual",
        "Medición de presión intraocular",
        "Fondo de ojo",
        "Lavado de oído",
        "Retiro de cuerpo extraño",
        "Adaptación de lentes de contacto",
        "Campimetría",
    ],
    "medicina_general": [
        "Consulta general",
        "Certificado médico",
        "Aplicación de inyección",
        "Curación de herida",
        "Toma de presión arterial",
    ],
    "pediatria": [
        "Consulta pediátrica",
        "Control del niño sano",
        "Aplicación de vacuna",
        "Valoración de crecimiento y desarrollo",
    ],
    "ginecologia": [
        "Consulta ginecológica",
        "Papanicolaou",
        "Colposcopía",
        "Control prenatal",
        "Ultrasonido obstétrico",
    ],
    "dermatologia": [
        "Consulta dermatológica",
        "Criocirugía",
        "Retiro de lunar o verruga",
        "Dermatoscopía",
        "Biopsia de piel",
    ],
    "psicologia": [
        "Primera sesión",
        "Sesión de seguimiento",
        "Terapia de pareja",
        "Evaluación psicológica",
    ],
    "psiquiatria": [
        "Consulta psiquiátrica",
        "Seguimiento de tratamiento",
        "Evaluación inicial",
    ],
    "nutricion": [
        "Consulta nutricional",
        "Plan alimenticio",
        "Medición de composición corporal",
        "Seguimiento mensual",
    ],
    "odontologia": [
        "Consulta y diagnóstico",
        "Limpieza dental",
        "Resina",
        "Extracción",
        "Blanqueamiento",
    ],
    "ortopedia": [
        "Consulta ortopédica",
        "Infiltración",
        "Colocación de férula o yeso",
        "Valoración de estudios de imagen",
    ],
    "cardiologia": [
        "Consulta cardiológica",
        "Electrocardiograma",
        "Prueba de esfuerzo",
        "Monitoreo Holter",
    ],
    "otorrinolaringologia": [
        "Consulta otorrinolaringológica",
        "Lavado de oído",
        "Endoscopía nasal",
        "Audiometría",
    ],
    "gastroenterologia": [
        "Consulta gastroenterológica",
        "Valoración de estudios",
        "Seguimiento de tratamiento",
    ],
    "neurologia": [
        "Consulta neurológica",
        "Electroencefalograma",
        "Valoración de estudios de imagen",
    ],
    "urologia": [
        "Consulta urológica",
        "Flujometría",
        "Ultrasonido de vías urinarias",
    ],
    "endocrinologia": [
        "Consulta endocrinológica",
        "Control de diabetes",
        "Control de tiroides",
    ],
}

# --- Alarm symptoms --------------------------------------------------------
# What makes the assistant escalate to the doctor instead of just booking.
# These are triage prompts for the doctor to curate, not a diagnostic tool:
# the assistant never diagnoses (patient prompt, critical rule 1).
GENERAL_SYMPTOMS: list[str] = [
    "Dolor severo que no cede",
    "Dificultad para respirar",
    "Fiebre muy alta",
    "Sangrado que no se detiene",
    "Pérdida de conciencia o desmayo",
]

SPECIALTY_SYMPTOMS: dict[str, list[str]] = {
    "oftalmologia": [
        "Pérdida súbita de la visión",
        "Dolor ocular intenso",
        "Destellos de luz o manchas flotantes nuevas",
        "Golpe o traumatismo en el ojo",
        "Sustancia química en el ojo",
        "Visión doble repentina",
    ],
    "medicina_general": [
        "Dolor en el pecho",
        "Dificultad para respirar",
        "Vómito o diarrea persistente",
        "Fiebre que no baja",
    ],
    "pediatria": [
        "Fiebre en menor de 3 meses",
        "Dificultad para respirar",
        "Vómito o diarrea persistente",
        "El niño no despierta o está muy decaído",
        "Convulsión",
    ],
    "ginecologia": [
        "Sangrado abundante",
        "Dolor abdominal intenso",
        "Disminución de movimientos del bebé",
        "Pérdida de líquido en el embarazo",
    ],
    "dermatologia": [
        "Lesión que crece o cambia rápido",
        "Ampollas extensas",
        "Reacción alérgica con hinchazón",
        "Herida con signos de infección",
    ],
    "psicologia": [
        "Ideas de hacerse daño",
        "Crisis de ansiedad severa",
        "No poder realizar actividades básicas",
    ],
    "psiquiatria": [
        "Ideas de hacerse daño o de dañar a alguien",
        "Suspensión abrupta del medicamento",
        "Efectos adversos del medicamento",
    ],
    "nutricion": [
        "Pérdida de peso acelerada",
        "Desmayos o mareos frecuentes",
    ],
    "odontologia": [
        "Dolor dental intenso",
        "Inflamación facial",
        "Golpe con diente fracturado o desprendido",
        "Sangrado que no se detiene",
    ],
    "ortopedia": [
        "Deformidad después de un golpe",
        "Imposibilidad de apoyar o mover la extremidad",
        "Hinchazón severa",
        "Pérdida de sensibilidad",
    ],
    "cardiologia": [
        "Dolor en el pecho",
        "Falta de aire en reposo",
        "Palpitaciones con mareo o desmayo",
        "Hinchazón repentina de piernas",
    ],
    "otorrinolaringologia": [
        "Dificultad para respirar o tragar",
        "Sangrado nasal que no se detiene",
        "Pérdida súbita de la audición",
        "Vértigo intenso",
    ],
    "gastroenterologia": [
        "Vómito con sangre",
        "Heces negras o con sangre",
        "Dolor abdominal intenso",
    ],
    "neurologia": [
        "Debilidad o adormecimiento de un lado del cuerpo",
        "Dificultad repentina para hablar",
        "Dolor de cabeza súbito e intenso",
        "Convulsión",
    ],
    "urologia": [
        "Imposibilidad de orinar",
        "Sangre en la orina",
        "Dolor intenso en el costado",
    ],
    "endocrinologia": [
        "Azúcar muy alta o muy baja",
        "Confusión o desorientación",
        "Vómito persistente en paciente diabético",
    ],
}

# --- Insurers --------------------------------------------------------------
# Canonical names for the major Mexican health insurers. `id` is what is
# stored; `label` is the official name shown to doctor and patient, so two
# offices never disagree on what the same insurer is called.
INSURERS: list[dict[str, str]] = [
    {"id": "gnp", "label": "GNP Seguros"},
    {"id": "axa", "label": "AXA Seguros"},
    {"id": "metlife", "label": "MetLife México"},
    {"id": "mapfre", "label": "Mapfre México"},
    {"id": "bbva", "label": "BBVA Seguros"},
    {"id": "banorte", "label": "Seguros Banorte"},
    {"id": "monterrey_new_york_life", "label": "Seguros Monterrey New York Life"},
    {"id": "allianz", "label": "Allianz México"},
    {"id": "zurich", "label": "Zurich México"},
    {"id": "atlas", "label": "Seguros Atlas"},
    {"id": "inbursa", "label": "Seguros Inbursa"},
    {"id": "qualitas", "label": "Quálitas"},
    {"id": "plan_seguro", "label": "Plan Seguro"},
    {"id": "vitamedica", "label": "VitaMédica"},
    {"id": "bupa", "label": "Bupa México"},
    {"id": "sura", "label": "Seguros SURA"},
    {"id": "hdi", "label": "HDI Seguros"},
    {"id": "chubb", "label": "Chubb Seguros México"},
]

# --- Intake questions ------------------------------------------------------
# What the assistant asks the patient before the visit. Kept short on purpose:
# a long interrogation over WhatsApp is abandoned halfway.
INTAKE_QUESTIONS: list[dict[str, str]] = [
    {
        "id": "motivo",
        "label": "Motivo de consulta",
        "description": "Por qué quiere venir el paciente.",
    },
    {
        "id": "desde_cuando",
        "label": "Desde cuándo",
        "description": "Hace cuánto empezó la molestia.",
    },
    {
        "id": "medicamentos",
        "label": "Medicamentos que toma",
        "description": "Tratamientos actuales del paciente.",
    },
    {
        "id": "primera_vez",
        "label": "Si es su primera vez con este padecimiento",
        "description": "Si ya lo ha consultado antes con alguien más.",
    },
]

_INSURER_LABELS: dict[str, str] = {i["id"]: i["label"] for i in INSURERS}
_INTAKE_LABELS: dict[str, str] = {q["id"]: q["label"] for q in INTAKE_QUESTIONS}
_SPECIALTY_LABELS: dict[str, str] = {s["id"]: s["label"] for s in SPECIALTIES}


def specialty_label(specialty_id: str | None) -> str | None:
    """Human label for a stored specialty id, or the raw value if custom."""
    if not specialty_id:
        return None
    return _SPECIALTY_LABELS.get(specialty_id, specialty_id)


def services_for(specialty_id: str | None) -> list[str]:
    """Suggested services for a specialty, always led by the two generics."""
    extra = SPECIALTY_SERVICES.get(specialty_id or "", [])
    # A specialty's own "consulta general" would duplicate "Primera consulta".
    return GENERAL_SERVICES + [s for s in extra if s not in GENERAL_SERVICES]


def symptoms_for(specialty_id: str | None) -> list[str]:
    """Suggested alarm symptoms for a specialty, falling back to the generics."""
    specific = SPECIALTY_SYMPTOMS.get(specialty_id or "")
    if not specific:
        return list(GENERAL_SYMPTOMS)
    return specific + [s for s in GENERAL_SYMPTOMS if s not in specific]


def insurer_labels(insurer_ids: list[str] | None) -> list[str]:
    """Official names for stored insurer ids, skipping unknown ones."""
    if not insurer_ids:
        return []
    return [_INSURER_LABELS[i] for i in insurer_ids if i in _INSURER_LABELS]


def intake_labels(question_ids: list[str] | None) -> list[str]:
    """Labels for stored intake question ids, skipping unknown ones."""
    if not question_ids:
        return []
    return [_INTAKE_LABELS[q] for q in question_ids if q in _INTAKE_LABELS]
