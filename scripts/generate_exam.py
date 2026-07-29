from __future__ import annotations

import json
import os
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from openai import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)

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


QUESTION_PLAN = (
    {"category": "Actualidad España", "freshness": "72h"},
    {"category": "Actualidad internacional", "freshness": "72h"},
    {"category": "RTVE y legislación audiovisual", "freshness": "static"},
    {
        "category": "Unión Europea e instituciones",
        "freshness": "current",
        "topicType": "office_holder",
    },
    {"category": "Economía y sociedad", "freshness": "7d"},
    {"category": "Cultura, ciencia y deporte", "freshness": "72h"},
    {"category": "Manual de Estilo, ética e igualdad", "freshness": "static"},
    {"category": "Conflictos, justicia y seguridad", "freshness": "72h"},
    {"category": "Actualidad España", "freshness": "7d"},
    {"category": "RTVE y legislación audiovisual", "freshness": "static"},
    {
        "category": "Unión Europea e instituciones",
        "freshness": "current",
        "topicType": "office_holder",
    },
    {"category": "Prevención de riesgos laborales", "freshness": "static"},
    {"category": "Actualidad internacional", "freshness": "7d"},
    {"category": "Economía y sociedad", "freshness": "30d"},
    {"category": "Cultura, ciencia y deporte", "freshness": "72h"},
    {"category": "Manual de Estilo, ética e igualdad", "freshness": "static"},
    {"category": "Conflictos, justicia y seguridad", "freshness": "5y"},
    {"category": "Actualidad España", "freshness": "7d"},
    {"category": "RTVE y legislación audiovisual", "freshness": "static"},
    {"category": "Actualidad internacional", "freshness": "5y"},
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
                "minItems": 26,
                "maxItems": 34,
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


def question_schema_for_slot(slot: dict[str, str]) -> dict[str, Any]:
    topic_type_schema: dict[str, Any]

    if "topicType" in slot:
        topic_type_schema = {
            "type": "string",
            "enum": [slot["topicType"]],
        }
    else:
        topic_type_schema = {
            "type": "string",
            "enum": list(TOPIC_TYPES),
        }

    return {
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
            "correctIndex": {
                "type": "integer",
                "minimum": 0,
                "maximum": 3,
            },
            "explanation": {"type": "string"},
            "category": {
                "type": "string",
                "enum": [slot["category"]],
            },
            "freshness": {
                "type": "string",
                "enum": [slot["freshness"]],
            },
            "topicType": topic_type_schema,
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
    }


def exam_schema() -> dict[str, Any]:
    question_properties = {
        f"q{number:02d}": question_schema_for_slot(slot)
        for number, slot in enumerate(QUESTION_PLAN, start=1)
    }

    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "level": {
                "type": "string",
                "enum": ["Alto", "Muy alto"],
            },
            "timeMinutes": {
                "type": "integer",
                "enum": [30],
            },
            "currentAffairsCutoff": {"type": "string"},
            "blocks": {
                "type": "array",
                "minItems": 6,
                "maxItems": 9,
                "items": {
                    "type": "string",
                    "enum": list(CATEGORIES),
                },
            },
            "questions": {
                "type": "object",
                "additionalProperties": False,
                "properties": question_properties,
                "required": list(question_properties),
            },
        },
        "required": [
            "level",
            "timeMinutes",
            "currentAffairsCutoff",
            "blocks",
            "questions",
        ],
    }


def unpack_questions(exam: dict[str, Any]) -> dict[str, Any]:
    questions = exam.get("questions")

    if isinstance(questions, dict):
        exam["questions"] = [
            questions[f"q{number:02d}"]
            for number in range(1, 21)
        ]

    return exam



def validate_research(dossier: dict[str, Any]) -> None:
    items = dossier.get("items")
    if not isinstance(items, list) or len(items) < 26:
        raise ValueError("La investigación no contiene suficientes hechos verificados.")
    valid_items = 0
    for item in items:
        if is_url(str(item.get("sourceUrl", ""))):
            valid_items += 1
    if valid_items < 26:
        raise ValueError("La investigación contiene fuentes no válidas.")


def validate_exam(exam: dict[str, Any]) -> None:
    questions = exam.get("questions")
    if not isinstance(questions, list) or len(questions) != 20:
        raise ValueError("El modelo no generó exactamente 20 preguntas.")

    for number, (question, slot) in enumerate(
        zip(questions, QUESTION_PLAN),
        start=1,
    ):
        if question.get("category") != slot["category"]:
            raise ValueError(
                f"La pregunta {number} debe pertenecer a "
                f"{slot['category']}."
            )

        if question.get("freshness") != slot["freshness"]:
            raise ValueError(
                f"La pregunta {number} debe tener antigüedad "
                f"{slot['freshness']}."
            )

        expected_type = slot.get("topicType")
        if expected_type and question.get("topicType") != expected_type:
            raise ValueError(
                f"La pregunta {number} debe ser de tipo "
                f"{expected_type}."
            )

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



def create_background_response(
    client: OpenAI,
    *,
    label: str,
    max_wait_seconds: int,
    **request: Any,
):
    """Ejecuta una respuesta larga en background y consulta su estado."""
    response = client.with_options(
        timeout=60.0,
        max_retries=2,
    ).responses.create(
        background=True,
        store=True,
        **request,
    )

    print(
        f"{label}: respuesta {response.id} iniciada con estado {response.status}.",
        flush=True,
    )

    deadline = time.monotonic() + max_wait_seconds

    while response.status in {"queued", "in_progress"}:
        if time.monotonic() >= deadline:
            try:
                client.responses.cancel(response.id)
            except Exception:
                pass

            raise RuntimeError(
                f"{label} superó el límite de "
                f"{max_wait_seconds // 60} minutos."
            )

        time.sleep(10)

        response = client.with_options(
            timeout=60.0,
            max_retries=2,
        ).responses.retrieve(response.id)

        print(
            f"{label}: estado {response.status}.",
            flush=True,
        )

    if response.status != "completed":
        error = getattr(response, "error", None)
        incomplete = getattr(response, "incomplete_details", None)
        raise RuntimeError(
            f"{label} terminó con estado {response.status}. "
            f"Error: {error or incomplete or 'sin detalle'}"
        )

    return response


def research_current_affairs(client: OpenAI, recent_questions: list[str]) -> dict[str, Any]:
    research_prompt = f"""
Eres un editor jefe de actualidad que prepara un dossier verificado para una oposición de
Información y Contenidos de RTVE. La fecha y hora de corte es {NOW.isoformat()} en Madrid.
Debes utilizar búsqueda web antes de responder.

Reúne entre 26 y 34 hechos candidatos, relevantes y preguntables:
- Al menos 8 hechos de las últimas 72 horas.
- Al menos 6 hechos de los últimos siete días.
- Al menos 3 hechos relevantes del último mes.
- Al menos 4 cargos o presidencias vigentes verificados hoy: España, autonomías, UE u
  organismos internacionales.
- Al menos 3 acontecimientos esenciales de los últimos cinco años que ayuden a comprender
  la agenda actual.
- Al menos 6 hechos estáticos obtenidos de fuentes oficiales del temario: dos sobre RTVE o
  legislación audiovisual; dos sobre Manual de Estilo, ética o igualdad; uno de prevención
  de riesgos; y uno sobre Unión Europea o instituciones del Estado.

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
            response = create_background_response(
                client,
                label="Investigación de actualidad",
                max_wait_seconds=720,
                model=MODEL,
                tools=[{"type": "web_search", "search_context_size": "medium"}],
                input=research_prompt,
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
Reproducir la dificultad, amplitud temática, concreción, ritmo y, especialmente, la
redacción del cuadernillo oficial de 2024 sin copiar ninguna pregunta. El resultado debe
parecer un fragmento nuevo de aquel cuadernillo: preguntas autónomas, sobrias, factuales
y mezcladas sin bloques visibles. La actualidad debe estar verificada mediante el dossier
obtenido hoy y debe tener mucho más peso cuanto más reciente sea.

MAPA EXACTO DE LAS 20 POSICIONES
Debes respetar literalmente esta categoría y antigüedad para cada número:
  1. Actualidad España — 72h.
  2. Actualidad internacional — 72h.
  3. RTVE y legislación audiovisual — static.
  4. Unión Europea e instituciones — current — cargo vigente.
  5. Economía y sociedad — 7d.
  6. Cultura, ciencia y deporte — 72h.
  7. Manual de Estilo, ética e igualdad — static.
  8. Conflictos, justicia y seguridad — 72h.
  9. Actualidad España — 7d.
 10. RTVE y legislación audiovisual — static.
 11. Unión Europea e instituciones — current — cargo vigente.
 12. Prevención de riesgos laborales — static.
 13. Actualidad internacional — 7d.
 14. Economía y sociedad — 30d.
 15. Cultura, ciencia y deporte — 72h.
 16. Manual de Estilo, ética e igualdad — static.
 17. Conflictos, justicia y seguridad — 5y.
 18. Actualidad España — 7d.
 19. RTVE y legislación audiovisual — static.
 20. Actualidad internacional — 5y.

No intercambies las categorías aunque una noticia pudiera encajar en dos bloques.
La posición 2 y la 13 deben ser inequívocamente de actualidad internacional,
no de conflictos. La posición 20 debe aportar contexto internacional de los
últimos cinco años.

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

REDACCIÓN OBLIGATORIA: IMITAR EL CUADERNILLO RTVE DE 2024
- La redacción debe parecer obra de un tribunal, no de un profesor ni de una IA.
- Predomina la pregunta factual, seca y concreta. No introduzcas explicaciones,
  contexto pedagógico ni razonamientos en el enunciado.
- Entre 17 y 19 enunciados deben adoptar forma interrogativa directa con signos
  ¿...?; una o dos preguntas pueden formularse como frase incompleta terminada
  en puntos suspensivos o dos puntos, para que las opciones completen la frase.
- Longitud orientativa del enunciado: entre 8 y 22 palabras. Se permiten hasta
  35 cuando sea imprescindible citar una ley, informe, declaración o antecedente.
- Alterna de forma natural estas entradas, sin convertirlas en una plantilla mecánica:
  “¿Quién...?”, “¿Cuál...?”, “¿Qué...?”, “¿En qué...?”, “¿Cuándo...?”,
  “¿Cuántos...?”, “¿Cómo...?”, “¿Por qué...?” y “Según [fuente], ¿...?”.
- Entre cuatro y seis preguntas deben comenzar o quedar claramente ancladas con
  “Según...” cuando la respuesta dependa de una ley, artículo, informe, manual,
  guía, organismo o autoridad concreta.
- En actualidad, utiliza fórmulas propias del cuadernillo: “este año”, “el pasado
  mes de...”, “en las últimas elecciones”, “actualmente” o una fecha concreta,
  siempre que resulten inequívocas respecto a la fecha del examen.
- Los nombres propios, cargos, organismos, leyes, premios, ciudades, países,
  obras, fechas y cifras deben aparecer con su denominación precisa.
- Como máximo una pregunta del examen puede utilizar una negación destacada
  (“NO” o “EXCEPTO”). No abuses de esta técnica.
- Evita expresiones impropias del examen real: “imagina que”, “supón que”,
  “en un escenario hipotético”, “como profesional”, “¿qué harías?”,
  “selecciona la opción más adecuada” o largos casos prácticos.
- Evita comenzar repetidamente con “¿Cuál de las siguientes afirmaciones...?”.
  Úsalo solo cuando sea natural en una pregunta normativa o institucional.
- No añadas pistas metalingüísticas como “basándote en el dossier”, “según la
  información proporcionada” o “de acuerdo con la noticia anterior”.

FORMA DE LAS OPCIONES
- Las cuatro opciones deben pertenecer a la misma clase de respuesta:
  cuatro personas, cuatro países, cuatro fechas, cuatro cifras, cuatro obras,
  cuatro instituciones o cuatro enunciados jurídicos comparables.
- Si se pregunta por una persona, lugar, fecha, cifra, partido, obra o institución,
  usa opciones breves, sin explicaciones añadidas.
- Si se pregunta por una norma o definición, usa oraciones completas y paralelas.
- No fuerces la misma longitud exacta en todas las opciones: el examen real no
  siempre lo hace. Evita únicamente que la correcta sea un evidente párrafo
  mientras las otras son palabras sueltas, salvo que el texto legal lo exija.
- Los distractores deben ser próximos y plausibles: cargos del mismo nivel,
  países de la misma región, fechas cercanas, cifras razonables, premios de la
  misma categoría, instituciones con competencias parecidas o conceptos legales
  vecinos.
- No uses opciones absurdas, humorísticas, genéricas ni manifiestamente falsas.
- No uses “todas las anteriores”, “ninguna de las anteriores”, “A y B” ni
  respuestas dobles.
- Escribe las opciones como respuestas autónomas, con mayúscula inicial y punto
  final cuando sean oraciones.

PATRONES QUE DEBEN APARECER EN EL CONJUNTO, NO EN TODAS LAS PREGUNTAS
- Cargo vigente: “¿Quién es actualmente...?” o “¿Quién ocupa...?”.
- Dato reciente: “¿Cuál fue...?”, “¿Cuántos...?” o “¿En qué ciudad/país...?”.
- Fuente o informe: “Según [organismo/informe], ¿...?”.
- Norma: “Según el artículo [número] de [ley], ¿...?” o una frase legal que
  deba completarse.
- Acontecimiento internacional: pregunta por protagonista, lugar, fecha,
  organismo, causa acreditada o consecuencia principal.
- Cultura y deporte: premiado, obra, resultado, sede, selección, competición o
  institución, con distractores del mismo ámbito.

ATRIBUCIÓN Y PRUDENCIA PERIODÍSTICA
- Cuando un hecho sea controvertido, disputado o dependa de una versión oficial,
  incorpora la atribución dentro del enunciado: “Según [autoridad/fuente]...”.
- No conviertas una acusación, estimación o versión de parte en un hecho absoluto.
- Si una cifra procede de una encuesta, balance o informe, menciona la fuente en
  el enunciado, como hace habitualmente el cuadernillo.

CONTROL FINAL DE ESTILO
Antes de devolver el JSON, revisa silenciosamente cada pregunta y corrige:
1. ¿Suena a pregunta de oposición RTVE y no a ejercicio didáctico?
2. ¿Pregunta un dato o contenido concreto?
3. ¿El enunciado es tan breve como permite la precisión?
4. ¿La atribución aparece cuando es necesaria?
5. ¿Las cuatro opciones son de la misma naturaleza?
6. ¿Los distractores podrían confundir a una persona razonablemente informada?
7. ¿La respuesta correcta no destaca por tono, detalle o longitud?
8. ¿No se repite una fórmula verbal de forma monótona?
9. ¿Se han eliminado erratas, ambigüedades y giros artificiales?

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
            response = create_background_response(
                client,
                label=f"Generación del examen (intento {attempt})",
                max_wait_seconds=600,
                model=MODEL,
                input=base_prompt + correction,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "rtve_journalist_daily_exam",
                        "strict": True,
                        "schema": exam_schema(),
                    }
                },
            )
            generated = unpack_questions(
                json.loads(response.output_text)
            )
            validate_exam(generated)
            return generated
        except (ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            print(f"Intento de examen {attempt} no válido: {exc}", file=sys.stderr)
            correction = (
                "\n\nCORRECCIÓN OBLIGATORIA PARA EL NUEVO INTENTO:\n"
                f"El intento anterior fue rechazado por este motivo: {exc}. "
                "Rehaz el examen completo, cumple exactamente todos los mínimos y "
                "aplica de nuevo las reglas de redacción del cuadernillo RTVE."
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
    client = OpenAI(
        max_retries=2,
        timeout=60.0,
    )

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
    except (APIConnectionError, APITimeoutError) as exc:
        cause = getattr(exc, "__cause__", None)
        print(
            "ERROR persistente de conexión con OpenAI después de los reintentos: "
            f"{cause or exc}",
            file=sys.stderr,
        )
        return 5
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
