from __future__ import annotations

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.modulos.common.permissions import rbac_permission

from .assistant import answer_question
from .chat import answer_chat
from .code_feedback import synthesize_code_feedback
from .dev_chat import answer_dev_chat
from .dev_export import build_feedback_markdown, default_filename
from .search import search_code, search_docs
from .skills.resumen import build_daily_summary
from .suggestions import SUGGESTION_GROUPS
from .synthesis import synthesize_answer


class KnowledgeSearchView(APIView):
    """RAG de documentación interna: retrieval determinista SIEMPRE; síntesis opcional.

    `GET ?q=...&limit=8&synthesize=1` — los resultados traen fuente (path + heading) y
    extracto resaltado. Con `synthesize=1` Y el kill switch encendido, `answer` trae la
    respuesta del LLM con citas [n]; si la IA está apagada o falla, `answer` es null y
    los resultados deterministas quedan igual (la búsqueda nunca depende de la IA).
    """

    permission_classes = [rbac_permission("knowledge.docs.read")]

    def get(self, request):
        query = (request.query_params.get("q") or "").strip()
        if not query:
            return Response({"detail": "q requerido."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            limit = int(request.query_params.get("limit", "8"))
        except (TypeError, ValueError):
            return Response({"detail": "limit debe ser entero."}, status=status.HTTP_400_BAD_REQUEST)

        results = search_docs(query, limit=limit)
        answer = None
        if request.query_params.get("synthesize") in ("1", "true"):
            answer = synthesize_answer(query, results)
        return Response(
            {
                "query": query,
                "results": results,
                "answer": answer,
                "ai_used": answer is not None,
            },
            status=status.HTTP_200_OK,
        )


class KnowledgeAssistantView(APIView):
    """Asistente del sistema: responde con DATOS reales o con la documentación.

    `GET ?q=...` → enruta a una consulta de datos (read-only, acotada a la empresa y al permiso
    del usuario) o, si es una pregunta de "cómo se usa", a la búsqueda en el manual. Respuesta:
    `{kind: "data"|"docs", answer, data?, results?, sources?, skill?, ai_used}`.
    El permiso base es `knowledge.docs.read`; cada consulta de datos exige además su propio permiso.
    """

    permission_classes = [rbac_permission("knowledge.docs.read")]

    def get(self, request):
        query = (request.query_params.get("q") or "").strip()
        if not query:
            return Response({"detail": "q requerido."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(answer_question(request=request, query=query), status=status.HTTP_200_OK)


class KnowledgeChatView(APIView):
    """Asistente CONVERSACIONAL (multi-turno) del sistema.

    `POST {messages: [{role, content}, ...]}` → `{reply, used_skills, sources, ai_used}`. El frontend
    manda el historial (sin estado en servidor). Las cifras vienen de las skills (read-only, acotadas
    a empresa + permiso); el LLM redacta y aconseja pero no inventa números. Detrás del kill switch:
    con la IA apagada degrada a la respuesta determinista. Permiso base `knowledge.docs.read`.
    """

    permission_classes = [rbac_permission("knowledge.docs.read")]

    def post(self, request):
        messages = request.data.get("messages") if isinstance(request.data, dict) else None
        if not isinstance(messages, list) or not messages:
            return Response({"detail": "messages requerido (lista no vacía)."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(answer_chat(request=request, messages=messages), status=status.HTTP_200_OK)


class KnowledgeSummaryView(APIView):
    """Panel "resumen del día": combina varias consultas operativas en una sola respuesta.

    `GET` → `{kind: "data", answer, data: {empresa, secciones: [...]}}`. Cada sección solo aparece
    si el usuario tiene su permiso (read-only, acotado a la empresa). Pensado para cargarse al abrir
    el asistente. El permiso base es `knowledge.docs.read`; cada sección se re-gatea adentro.
    """

    permission_classes = [rbac_permission("knowledge.docs.read")]

    def get(self, request):
        return Response(
            {"kind": "data", **build_daily_summary(request=request)}, status=status.HTTP_200_OK
        )


class KnowledgeSuggestionsView(APIView):
    """Sugerencias iniciales del asistente — "¿con qué te puedo ayudar?".

    `GET` → grupos de preguntas frecuentes (tema + ícono + preguntas) para mostrar al
    entrar, antes de escribir nada. Cada pregunta se manda tal cual al buscador al clicarla.
    """

    permission_classes = [rbac_permission("knowledge.docs.read")]

    def get(self, request):
        return Response({"groups": SUGGESTION_GROUPS}, status=status.HTTP_200_OK)


class KnowledgeDevFeedbackView(APIView):
    """Asistente de DESARROLLO (solo dev/dueño): feedback rápido sobre el CÓDIGO de un flujo.

    `GET ?q=...&limit=8&synthesize=1` → recupera fragmentos del código fuente indexado
    (backend + frontend) para el flujo y, con `synthesize=1` Y el kill switch encendido,
    agrega una nota del LLM local (`answer`) que señala huecos evidentes. El retrieval es
    DETERMINISTA y funciona SIEMPRE (offline); la nota IA es opcional y degradable.

    Permiso `knowledge.dev.read` (NO `knowledge.docs.read`: el código no es para usuarios
    finales). Para el diagnóstico de FONDO de un flujo, usar la skill de Claude `feedback-flujo`.
    """

    permission_classes = [rbac_permission("knowledge.dev.read")]

    def get(self, request):
        query = (request.query_params.get("q") or "").strip()
        if not query:
            return Response({"detail": "q requerido."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            limit = int(request.query_params.get("limit", "8"))
        except (TypeError, ValueError):
            return Response({"detail": "limit debe ser entero."}, status=status.HTTP_400_BAD_REQUEST)

        results = search_code(query, limit=limit)
        answer = None
        if request.query_params.get("synthesize") in ("1", "true"):
            answer = synthesize_code_feedback(query, results)
        return Response(
            {
                "query": query,
                "results": results,
                "answer": answer,
                "ai_used": answer is not None,
            },
            status=status.HTTP_200_OK,
        )


class KnowledgeDevChatView(APIView):
    """Asistente de DESARROLLO CONVERSACIONAL sobre el código (solo dev/dueño).

    `POST {messages: [{role, content}, ...]}` → `{reply, used_files, fragments, ai_used}`. Multi-turno
    (el frontend manda el historial). El LLM local explica cómo está cableado un flujo usando SOLO los
    fragmentos de código recuperados; degrada a la ubicación determinista si la IA está apagada o falla.
    Es la pata "consulto al LLM local" del loop: la conversación se exporta y se lleva a Claude.
    Permiso `knowledge.dev.read`.
    """

    permission_classes = [rbac_permission("knowledge.dev.read")]

    def post(self, request):
        messages = request.data.get("messages") if isinstance(request.data, dict) else None
        if not isinstance(messages, list) or not messages:
            return Response({"detail": "messages requerido (lista no vacía)."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(answer_dev_chat(request=request, messages=messages), status=status.HTTP_200_OK)


class KnowledgeDevExportView(APIView):
    """Exporta la conversación del asistente de desarrollo como feedback Markdown (solo dev/dueño).

    `POST {messages: [...], fragments?: [...], title?: str}` → `{markdown, filename}`. El packet incluye
    la conversación + los fragmentos de código REALES citados (fuente de verdad) para llevar a Claude.
    Permiso `knowledge.dev.read`.
    """

    permission_classes = [rbac_permission("knowledge.dev.read")]

    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        messages = data.get("messages")
        if not isinstance(messages, list) or not messages:
            return Response({"detail": "messages requerido (lista no vacía)."}, status=status.HTTP_400_BAD_REQUEST)
        fragments = data.get("fragments")
        fragments = fragments if isinstance(fragments, list) else []
        title = str(data.get("title") or "Feedback de código")[:120]
        markdown = build_feedback_markdown(messages=messages, fragments=fragments, title=title)
        return Response({"markdown": markdown, "filename": default_filename(title)}, status=status.HTTP_200_OK)
