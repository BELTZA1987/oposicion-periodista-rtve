# Oposición Periodista RTVE — Información y Contenidos

Web interactiva paralela a la preparación de Edición y Montaje.

## Qué incluye

- Catálogo de exámenes, estados y notas.
- 20 preguntas diarias con cuatro opciones.
- Corrección oficial: +1 correcta, -1/3 incorrecta y 0 en blanco.
- Fuentes enlazadas tras corregir cada pregunta.
- Investigación web diaria de noticias y cargos vigentes.
- Prioridad para las últimas 72 horas y los últimos siete días.
- Temario completo de Información y Contenidos publicado para la Convocatoria 1/2022.
- Estilo inspirado en el cuadernillo oficial de 2024, sin copiar preguntas.
- Publicación automática en GitHub Pages.

## Crear el repositorio

1. Crea un repositorio público nuevo, por ejemplo `oposicion-periodista-rtve`.
2. Sube todos los archivos de esta carpeta a la raíz.
3. En `Settings → Actions → General` selecciona:
   - `Allow all actions and reusable workflows`.
   - `Read and write permissions`.
   - No hace falta permitir que Actions apruebe pull requests.
4. En `Settings → Secrets and variables → Actions` crea:
   - Nombre: `OPENAI_API_KEY`
   - Valor: tu clave de la API de OpenAI.
5. En `Settings → Pages → Build and deployment → Source` selecciona `GitHub Actions`.

## Primera ejecución

1. Abre `Actions → RTVE Periodista - Examen diario`.
2. Pulsa `Run workflow`.
3. Activa `force`.
4. Espera a que termine en verde.
5. Después se ejecutará `Publicar web de Periodista en GitHub Pages`.

## Horario

- Ejecución principal: 09:07, zona `Europe/Madrid`.
- Intento de seguridad: 09:37. Si el examen de ese día ya existe, termina antes de investigar
  y no consume la API.

GitHub puede retrasar algunos minutos los trabajos programados.

## Actualidad

El generador realiza dos fases:

1. Investiga mediante la herramienta de búsqueda web de la API de OpenAI y construye un
   dossier de hechos y cargos verificados.
2. Genera un examen estructurado con fuentes, lo valida y lo incorpora a `data/exams.json`.

La búsqueda web implica un coste de API superior al generador técnico de Edición, aunque
sigue siendo un uso pequeño para un examen diario.

## Archivos principales

- `reference/rtve_topics.txt`: temario oficial y política de actualidad.
- `reference/exam_style_2024.txt`: patrones del examen de referencia.
- `scripts/generate_exam.py`: investigación, generación y validación.
- `.github/workflows/journalist-daily-exam.yml`: horario diario.
- `.github/workflows/deploy-pages.yml`: publicación de la web.

## Resultados

El progreso se guarda en `localStorage` bajo el dominio de la nueva web. No se comparte con
la web de Edición ni se sincroniza entre dispositivos.
