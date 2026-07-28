from __future__ import annotations

import json
import os
import random
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from openai import APIError, AuthenticationError, OpenAI, RateLimitError

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data" / "exams.json"
TOPICS_FILE = ROOT / "reference" / "rtve_topics.txt"
STYLE_FILE = ROOT / "reference" / "exam_style_2024.txt"

MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")
FORCE_CREATE = os.getenv("FORCE_CREATE", "false").lower() in {"1", "true", "yes"}
NOW = datetime.now(ZoneInfo("Europe/Madrid"))
TODAY = NOW.date().isoformat()

CATEGORIES = (
    "Actualidad España",
    "Actualidad internacional",
    "Unión Europea e instituciones",
    "Economía y sociedad",
    "Cultura, ciencia y deporte",
    "RTVE y legislación audiovisual",
    "Manual de Estilo, ética e igualdad",
    "Prevención de riesgos laborales",
    "Conflictos, justicia y seguridad",
)

FRESHNESS_VALUES = ("72h", "7d", "30d", "current", "5y", "static")
TOPIC_TYPES = (
    "recent_event",
    "office_holder",
    "politics",
    "conflict",
    "economy",
    "society",
    "culture",
    "science",
    "sport",
    "law_rtve",
    "institutions",
    "ethics",
    "prl",
)

BANNED_OPTIONS = (
    "todas las anteriores",
    "ninguna de las anteriores",
    "a y b son correctas",
    "todas son correctas",
)


def load_data() -> dict[str, Any]:
    if not DATA_FILE.exists():
        raise FileNotFoundError(f"No existe {DATA_FILE}")
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    if not isinstance(data.get("exams"), list):
        raise ValueError("data/exams.json no contiene una lista 'exams'.")
    return data


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold().strip())


def is_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False


def research_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "asOf": {"type": "string"},
            "items": {
                "type": "array",
                "minItems": 34,
                "maxItems": 48,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "headline": {"type": "string"},
                        "fact": {"type": "string"},
                        "theme": {"type": "string"},
                        "region": {"type": "string"},
                        "freshness": {
                            "type": "string",
                            "enum": ["72h", "7d", "30d", "current", "5y", "static"],
                        },
                        "importance": {"type": "integer", "minimum": 1, "maximum": 5},
                        "sourceTitle": {"type": "string"},
                        "sourceUrl": {"type": "string"},
                        "publishedDate": {"type": "string"},
                        "eventDate": {"type": "string"},
                        "verificationNote": {"type": "string"},
                    },
                    "required": [
                        "headline",
                        "fact",
                        "theme",
                        "region",
                        "freshness",
                        "importance",
                        "sourceTitle",
                        "sourceUrl",
                        "publishedDate",
                        "eventDate",
                        "verificationNote",
                    ],
                },
            },
        },
        "required": ["asOf", "items"],
    }


def exam_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "level": {"type": "string", "enum": ["Alto", "Muy alto"]},
            "timeMinutes": {"type": "integer", "enum": [30]},
            "currentAffairsCutoff": {"type": "string"},
            "blocks": {
                "type": "array",
                "minItems": 6,
                "maxItems": 9,
                "items": {"type": "string", "enum": list(CATEGORIES)},
            },
            "questions": {
                "type": "array",
                "minItems": 20,
                "maxItems": 20,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "prompt": {"type": "string"},
                        "options": {
                            "type": "array",
                            "minItems": 4,
                            "maxItems": 4,
                            "items": {"type": "string"},
                        },
                        "correctIndex": {"type": "integer", "minimum": 0, "maximum": 3},
                        "explanation": {"type": "string"},
                        "category": {"type": "string", "enum": list(CATEGORIES)},
                        "freshness": {"type": "string", "enum": list(FRESHNESS_VALUES)},
                        "topicType": {"type": "string", "enum": list(TOPIC_TYPES)},
                        "sourceTitle": {"type": "string"},
                        "sourceUrl": {"type": "string"},
                        "sourceDate": {"type": "string"},
                    },
                    "required": [
                        "prompt",
                        "options",
                        "correctIndex",
                        "explanation",
                        "category",
                        "freshness",
                        "topicType",
                        "sourceTitle",
                        "sourceUrl",
                        "sourceDate",
                    ],
                },
            },
        },
        "required": ["level", "timeMinutes", "currentAffairsCutoff", "blocks", "questions"],
    }


def validate_research(dossier: dict[str, Any]) -> None:
    items = dossier.get("items")
    if not isinstance(items, list) or len(items) < 34:
        raise ValueError("La investigación no contiene suficientes hechos verificados.")
    valid_items = 0
    for item in items:
        if is_url(str(item.get("sourceUrl", ""))):
            valid_items += 1
    if valid_items < 34:
        raise ValueError("La investigación contiene fuentes no válidas.")


def validate_exam(exam: dict[str, Any]) -> None:
    questions = exam.get("questions")
    if not isinstance(questions, list) or len(questions) != 20:
        raise ValueError("El modelo no generó exactamente 20 preguntas.")

    prompts: set[str] = set()
    category_counts: dict[str, int] = {}
    freshness_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}

    for number, question in enumerate(questions, start=1):
        prompt = str(question.get("prompt", "")).strip()
        options = question.get("options")
        correct = question.get("correctIndex")
        explanation = str(question.get("explanation", "")).strip()
        category = str(question.get("category", "")).strip()
        freshness = str(question.get("freshness", "")).strip()
        topic_type = str(question.get("topicType", "")).strip()
        source_url = str(question.get("sourceUrl", "")).strip()

        normalized_prompt = normalize(prompt)
        if len(prompt) < 20 or normalized_prompt in prompts:
            raise ValueError(f"Pregunta {number} vacía, breve o duplicada.")
        prompts.add(normalized_prompt)

        if not isinstance(options, list) or len(options) != 4:
            raise ValueError(f"La pregunta {number} no tiene cuatro opciones.")
        normalized_options = [normalize(str(option)) for option in options]
        if any(not option for option in normalized_options) or len(set(normalized_options)) != 4:
            raise ValueError(f"Opciones vacías o repetidas en la pregunta {number}.")
        if any(banned in option for option in normalized_options for banned in BANNED_OPTIONS):
            raise ValueError(f"Opción global no permitida en la pregunta {number}.")
        if not isinstance(correct, int) or correct not in range(4):
            raise ValueError(f"Respuesta correcta inválida en la pregunta {number}.")
        if len(explanation) < 45:
            raise ValueError(f"Explicación insuficiente en la pregunta {number}.")
        if category not in CATEGORIES:
            raise ValueError(f"Categoría inválida en la pregunta {number}.")
        if freshness not in FRESHNESS_VALUES:
            raise ValueError(f"Antigüedad inválida en la pregunta {number}.")
        if topic_type not in TOPIC_TYPES:
            raise ValueError(f"Tipo temático inválido en la pregunta {number}.")
        if not is_url(source_url):
            raise ValueError(f"Fuente inválida en la pregunta {number}.")

        category_counts[category] = category_counts.get(category, 0) + 1
        freshness_counts[freshness] = freshness_counts.get(freshness, 0) + 1
        type_counts[topic_type] = type_counts.get(topic_type, 0) + 1

    minimum_categories = {
        "Actualidad España": 3,
        "Actualidad internacional": 2,
        "Unión Europea e instituciones": 2,
        "Economía y sociedad": 2,
        "Cultura, ciencia y deporte": 2,
        "RTVE y legislación audiovisual": 3,
        "Manual de Estilo, ética e igualdad": 2,
        "Prevención de riesgos laborales": 1,
        "Conflictos, justicia y seguridad": 2,
    }
    for category, minimum in minimum_categories.items():
        if category_counts.get(category, 0) < minimum:
            raise ValueError(f"Faltan preguntas de {category}: mínimo {minimum}.")

    minimum_freshness = {
        "72h": 5,
        "7d": 4,
        "current": 2,
        "30d": 1,
        "5y": 2,
        "static": 4,
    }
    for freshness, minimum in minimum_freshness.items():
        if freshness_counts.get(freshness, 0) < minimum:
            raise ValueError(f"Faltan preguntas con antigüedad {freshness}: mínimo {minimum}.")

    if type_counts.get("office_holder", 0) < 2:
        raise ValueError("El examen debe incluir al menos dos cargos vigentes.")


def balance_answers(exam: dict[str, Any], seed: int) -> None:
    rng = random.Random(seed)
    targets = [0, 1, 2, 3] * 5
    rng.shuffle(targets)
    for question, target in zip(exam["questions"], targets):
        options = list(question["options"])
        current = question["correctIndex"]
        options[current], options[target] = options[target], options[current]
        question["options"] = options
        question["correctIndex"] = target


def research_current_affairs(client: OpenAI, recent_questions: list[str]) -> dict[str, Any]:
    research_prompt = f"""
Eres un editor jefe de actualidad que prepara un dossier verificado para una oposición de
Información y Contenidos de RTVE. La fecha y hora de corte es {NOW.isoformat()} en Madrid.
Debes utilizar búsqueda web antes de responder.

Reúne entre 34 y 48 hechos candidatos, relevantes y preguntables:
- Al menos 10 hechos de las últimas 72 horas.
- Al menos 8 hechos de los últimos siete días.
- Al menos 4 hechos relevantes del último mes.
- Al menos 4 cargos o presidencias vigentes verificados hoy: España, autonomías, UE u
  organismos internacionales.
- Al menos 4 acontecimientos esenciales de los últimos cinco años que ayuden a comprender
  la agenda actual.
- Al menos 8 hechos estáticos obtenidos de fuentes oficiales del temario: tres sobre RTVE o
  legislación audiovisual; dos sobre Manual de Estilo, ética o igualdad; uno de prevención
  de riesgos; y dos sobre Unión Europea o instituciones del Estado.

Cubre de manera equilibrada política española, Unión Europea, política internacional,
economía, sociedad, justicia, conflictos bélicos y seguridad, ciencia, cultura y deporte.
Da mayor importancia a las noticias de las últimas 72 horas. Descarta rumores, opinión,
noticias menores, resultados en curso y datos inestables sin atribución.

Jerarquía de fuentes: fuentes oficiales y documentos primarios; Reuters, AP o EFE; RTVE,
BBC y otros medios de referencia. Para cargos vigentes usa preferentemente la web oficial
de la institución. Para legislación, Manual de Estilo, igualdad y PRL usa BOE, RTVE, UE,
UNESCO, FIP u otra fuente primaria. Para conflictos o hechos discutidos, formula el hecho
con atribución y explica brevemente cómo se verificó.

Cada sourceUrl debe ser una URL real de la fuente utilizada. publishedDate y eventDate deben
usar YYYY-MM-DD cuando se conozcan. freshness solo puede ser 72h, 7d, 30d, current, 5y o
static.

Evita hechos demasiado próximos a estas preguntas recientes:
{chr(10).join('- ' + q for q in recent_questions[-160:]) or '- No hay historial.'}
""".strip()

    last_error: Exception | None = None
    for attempt in range(1, 3):
        try:
            response = client.responses.create(
                model=MODEL,
                tools=[{"type": "web_search", "search_context_size": "high"}],
                input=research_prompt,
                store=False,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "journalist_current_affairs_research",
                        "strict": True,
                        "schema": research_schema(),
                    }
                },
            )
            dossier = json.loads(response.output_text)
            validate_research(dossier)
            return dossier
        except (ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            print(f"Intento de investigación {attempt} no válido: {exc}", file=sys.stderr)

    raise RuntimeError(f"No se pudo obtener un dossier válido: {last_error}")


def generate_exam(
    client: OpenAI,
    exam_id: str,
    topics: str,
    style: str,
    dossier: dict[str, Any],
    recent_questions: list[str],
) -> dict[str, Any]:
    base_prompt = f"""
Actúa como miembro experto del tribunal examinador de RTVE para la ocupación tipo
Información y Contenidos. Genera el EXAMEN {exam_id}, de 20 preguntas, a fecha {TODAY}.

OBJETIVO
Reproducir la dificultad, amplitud temática, concreción y ritmo del cuadernillo oficial de
2024 sin copiar ninguna pregunta. La actualidad debe estar verificada mediante el dossier
obtenido hoy y debe tener mucho más peso cuanto más reciente sea.

COMPOSICIÓN OBLIGATORIA
- Exactamente 20 preguntas, cuatro opciones y una sola correcta.
- Tiempo recomendado: exactamente 30 minutos.
- Categorías mínimas:
  * 3 Actualidad España.
  * 2 Actualidad internacional.
  * 2 Unión Europea e instituciones.
  * 2 Economía y sociedad.
  * 2 Cultura, ciencia y deporte.
  * 3 RTVE y legislación audiovisual.
  * 2 Manual de Estilo, ética e igualdad.
  * 1 Prevención de riesgos laborales.
  * 2 Conflictos, justicia y seguridad.
- Antigüedad mínima:
  * 5 preguntas sobre hechos de las últimas 72 horas.
  * 4 de los últimos siete días.
  * 2 sobre cargos vigentes comprobados hoy.
  * 1 del último mes.
  * 2 de contexto de los últimos cinco años.
  * 4 estáticas del temario oficial.
- Al menos dos preguntas deben preguntar por un cargo o presidencia vigente.
- Mezcla las materias; no agrupes las preguntas por bloques.

ESTILO
- Entre 14 y 16 preguntas directas de conocimiento factual.
- El resto puede exigir distinguir normas, instituciones o conceptos próximos.
- Usa quién, cuál, cuándo, dónde, cuántos, qué organismo o qué afirmación es correcta.
- Puedes incluir una o dos preguntas con NO o EXCEPTO, destacando la negación.
- Distractores próximos y plausibles: otros cargos, países, fechas, cifras, premios,
  instituciones o conceptos del mismo ámbito.
- No uses opciones absurdas, “todas”, “ninguna” ni combinaciones de respuestas.
- No hagas que la correcta sea reconocible por su longitud o tono.
- No imites erratas del examen histórico.

FIABILIDAD
- Usa exclusivamente hechos presentes en el dossier, tanto para actualidad como para
  normativa y contenidos estáticos.
- Conserva una fuente real que sustente cada respuesta.
- No inventes artículos, cifras, fechas, cargos ni URLs.
- Si un hecho es controvertido, formula la pregunta con atribución clara.
- La explicación debe justificar la correcta y distinguirla del distractor más cercano.

CONTROL DE REPETICIONES
- No copies ni reformules superficialmente las preguntas recientes.
- Se puede repetir un concepto central solo desde otro enfoque o con una actualización real.

TEMARIO COMPLETO:
{topics}

GUÍA DE ESTILO DEL EXAMEN OFICIAL:
{style}

DOSSIER VERIFICADO HOY:
{json.dumps(dossier, ensure_ascii=False, indent=2)}

PREGUNTAS RECIENTES A EVITAR:
{chr(10).join('- ' + q for q in recent_questions[-200:]) or '- No hay historial.'}

Devuelve únicamente el JSON exigido por el esquema.
""".strip()

    last_error: Exception | None = None
    correction = ""
    for attempt in range(1, 4):
        try:
            response = client.responses.create(
                model=MODEL,
                input=base_prompt + correction,
                store=False,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "rtve_journalist_daily_exam",
                        "strict": True,
                        "schema": exam_schema(),
                    }
                },
            )
            generated = json.loads(response.output_text)
            validate_exam(generated)
            return generated
        except (ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            print(f"Intento de examen {attempt} no válido: {exc}", file=sys.stderr)
            correction = (
                "\n\nCORRECCIÓN OBLIGATORIA PARA EL NUEVO INTENTO:\n"
                f"El intento anterior fue rechazado por este motivo: {exc}. "
                "Rehaz el examen completo y cumple exactamente todos los mínimos."
            )

    raise RuntimeError(f"No se pudo generar un examen válido: {last_error}")

def main() -> int:
    if not os.getenv("OPENAI_API_KEY"):
        print("ERROR: falta el secreto OPENAI_API_KEY.", file=sys.stderr)
        return 2

    data = load_data()
    existing: list[dict[str, Any]] = data["exams"]

    if not FORCE_CREATE and any(exam.get("date") == TODAY for exam in existing):
        print(f"Ya existe un examen con fecha {TODAY}; no se crea un duplicado.")
        return 0

    numeric_ids = [
        int(str(exam.get("id", "")).strip())
        for exam in existing
        if str(exam.get("id", "")).strip().isdigit()
    ]
    next_number = max(numeric_ids, default=0) + 1
    exam_id = f"{next_number:03d}"

    recent_questions = [
        str(question.get("prompt", "")).strip()
        for exam in existing[:12]
        for question in exam.get("questions", [])
        if str(question.get("prompt", "")).strip()
    ]

    topics = TOPICS_FILE.read_text(encoding="utf-8")
    style = STYLE_FILE.read_text(encoding="utf-8")
    client = OpenAI()

    try:
        print("Investigando actualidad y cargos vigentes...")
        dossier = research_current_affairs(client, recent_questions)
        print(f"Dossier verificado: {len(dossier['items'])} hechos candidatos.")

        print("Generando examen...")
        generated = generate_exam(
            client=client,
            exam_id=exam_id,
            topics=topics,
            style=style,
            dossier=dossier,
            recent_questions=recent_questions,
        )
    except AuthenticationError as exc:
        print("ERROR: la clave OPENAI_API_KEY no es válida o no tiene acceso.", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 3
    except RateLimitError as exc:
        print("ERROR: falta saldo, cuota o se alcanzó un límite de la API.", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 4
    except APIError as exc:
        print(f"ERROR de OpenAI API: {exc}", file=sys.stderr)
        return 5
    except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"ERROR de validación del examen: {exc}", file=sys.stderr)
        return 6

    balance_answers(generated, seed=next_number)

    exam = {
        "id": exam_id,
        "title": f"Examen {exam_id}",
        "date": TODAY,
        **generated,
    }

    data["exams"] = [exam] + existing
    data["updatedAt"] = NOW.isoformat()
    DATA_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(
        f"Creado {exam['title']} con 20 preguntas, actualidad hasta {TODAY} "
        f"y respuestas equilibradas: 5 A, 5 B, 5 C y 5 D."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
