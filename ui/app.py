import os
import time

import httpx
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000")

st.set_page_config(page_title="Data Quality Intelligence Platform", layout="wide")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SEVERITY_COLORS = {
    "critical": "red",
    "high": "orange",
    "warning": "#e6b800",
    "info": "#0066cc",
}

PHASE_TO_AGENTS: dict[str, list[str]] = {
    "initial": [],
    "detection_complete": ["validation", "detection"],
    "diagnosis_complete": ["validation", "detection", "diagnosis", "lineage"],
    "remediation_complete": [
        "validation",
        "detection",
        "diagnosis",
        "lineage",
        "business_impact",
        "repair",
    ],
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@st.cache_data(ttl=5)
def fetch_health() -> dict:
    try:
        r = httpx.get(f"{API_URL}/health", timeout=5)
        return r.json()
    except Exception:
        return {"status": "degraded", "checks": {}, "cost_session": {}}


def api_post(path: str, payload: dict) -> dict:
    try:
        r = httpx.post(f"{API_URL}{path}", json=payload, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def api_get(path: str, params: dict | None = None) -> dict | list:
    try:
        r = httpx.get(f"{API_URL}{path}", params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def severity_badge(severity: str) -> str:
    color = SEVERITY_COLORS.get((severity or "").lower(), "gray")
    label = (severity or "unknown").upper()
    return f'<span style="color:{color};font-weight:bold;font-size:1.1em">■ {label}</span>'


def render_results(state: dict) -> None:
    """Render full investigation results after workflow_complete."""
    severity = state.get("severity")
    if severity:
        st.markdown(severity_badge(severity), unsafe_allow_html=True)

    errors = state.get("errors") or []
    if errors:
        with st.expander("⚠️ Errors", expanded=False):
            for err in errors:
                st.error(err)

    diagnosis = state.get("diagnosis_result") or {}
    if diagnosis:
        st.markdown(f"**Root cause:** {diagnosis.get('root_cause', '—')}")
        st.markdown(f"**Confidence:** {diagnosis.get('confidence', 0) * 100:.0f}%")
        if diagnosis.get("estimated_impact_records"):
            st.markdown(f"**Affected records:** ~{diagnosis['estimated_impact_records']:,}")

    col1, col2 = st.columns(2)

    with col1:
        detection = state.get("detection_result") or {}
        if detection:
            with st.expander("Detection Result", expanded=True):
                st.markdown(f"Anomaly detected: **{detection.get('anomaly_detected')}**")
                st.markdown(f"Type: `{detection.get('anomaly_type', '—')}`")
                st.markdown(f"Confidence: {detection.get('confidence', 0) * 100:.0f}%")
                past = detection.get("similar_past_anomalies") or []
                if past:
                    st.markdown("**Similar past anomalies:**")
                    for a in past[:3]:
                        aid = a.get("anomaly_id") or a.get("id", "?")
                        st.caption(f"• {aid}: {a.get('resolution', '?')}")

        lineage = state.get("lineage_result") or {}
        if lineage:
            with st.expander("Lineage Result", expanded=False):
                st.markdown(f"Impact radius: **{lineage.get('impact_radius', 0)} nodes**")
                st.markdown(f"Critical path breached: **{lineage.get('critical_path_breached')}**")
                downstream = lineage.get("downstream_tables") or []
                if downstream:
                    st.markdown("**Downstream:** " + ", ".join(downstream))

    with col2:
        impact = state.get("business_impact") or {}
        if impact:
            with st.expander("Business Impact", expanded=True):
                st.markdown(f"Criticality: **{impact.get('business_criticality', '—')}**")
                st.markdown(f"Escalation required: **{impact.get('escalation_required')}**")
                contacts = impact.get("escalation_contacts") or []
                if contacts:
                    st.markdown("**Contacts:** " + ", ".join(contacts))
                for sla in (impact.get("affected_slas") or [])[:3]:
                    icon = "🔴" if sla.get("breached") else "🟡"
                    st.caption(f"{icon} {sla.get('table', '?')} (SLA: {sla.get('sla_hours')}h)")

        plan = state.get("remediation_plan") or {}
        if plan:
            with st.expander("Remediation Plan", expanded=True):
                st.markdown(f"Action: **{plan.get('recommended_action', '—')}**")
                st.markdown(
                    f"Risk: `{plan.get('risk_level', '—')}` · Est. {plan.get('estimated_duration_minutes', '?')} min"
                )
                if plan.get("playbook_reference"):
                    st.caption(f"Playbook: {plan['playbook_reference']}")
                for i, step in enumerate((plan.get("steps") or []), 1):
                    st.caption(f"{i}. {step}")

    outcome = state.get("remediation_result") or {}
    if outcome:
        with st.expander("Remediation Outcome", expanded=False):
            st.markdown(f"Status: **{outcome.get('status', '—')}**")
            st.markdown(f"Action taken: {outcome.get('action_taken', '—')}")
            if outcome.get("records_affected"):
                st.markdown(f"Records affected: {outcome['records_affected']}")

    latencies = state.get("agent_latencies") or {}
    if latencies:
        st.subheader("Agent Latencies (ms)")
        st.bar_chart(latencies)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("Data Quality\nIntelligence Platform")
    st.divider()

    health = fetch_health()
    status = health.get("status", "degraded")
    badge_color = "green" if status == "healthy" else "red"
    st.markdown(
        f'<span style="color:{badge_color};font-size:1.2em">● {status.upper()}</span>',
        unsafe_allow_html=True,
    )
    for svc, svc_status in health.get("checks", {}).items():
        icon = "✅" if svc_status == "healthy" else "❌"
        st.caption(f"{icon} {svc}")

    st.divider()
    cost = health.get("cost_session") or {}
    st.metric("Session Cost (USD)", f"${cost.get('session_total_usd', 0.0):.4f}")
    st.caption(f"Investigations: {cost.get('investigation_count', 0)}")

    st.divider()
    if st.button("🔄 Reset Demo", use_container_width=True):
        st.info("Run `bash scripts/reset_demo.sh` in a terminal to fully reset.")

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tab1, tab2, tab3 = st.tabs(["▶ Run Investigation", "📋 History", "🔍 Knowledge Base"])

# ===========================================================================
# TAB 1 — Run Investigation
# ===========================================================================

with tab1:
    st.header("Run Investigation")

    with st.form("investigation_form"):
        col1, col2 = st.columns(2)
        with col1:
            dataset_id = st.text_input("Dataset ID", value="orders_2026_03")
            table_name = st.text_input("Table Name", value="orders")
        with col2:
            alert_type = st.selectbox(
                "Alert Type",
                ["null_spike", "volume_drop", "schema_drift", "freshness", "manual"],
            )
        description = st.text_area(
            "Description",
            value="Noticed customer_id column has unusually high null rate this morning",
            height=80,
        )
        submitted = st.form_submit_button("▶ Run Investigation", use_container_width=True)

    if submitted:
        resp = api_post(
            "/api/v1/investigations",
            {
                "dataset_id": dataset_id,
                "table_name": table_name,
                "alert_type": alert_type,
                "description": description,
            },
        )
        if "error" in resp:
            st.error(f"Failed to start investigation: {resp['error']}")
        else:
            st.session_state["active_id"] = resp["investigation_id"]
            st.session_state["poll_complete"] = False
            st.success(f"Investigation started: `{resp['investigation_id']}`")

    active_id = st.session_state.get("active_id")

    if active_id and not st.session_state.get("poll_complete"):
        st.markdown(f"**Tracking:** `{active_id}`")

        phase_box = st.empty()
        severity_box = st.empty()
        result_box = st.empty()

        state = api_get(f"/api/v1/investigations/{active_id}")

        if isinstance(state, dict) and "error" not in state:
            phase = state.get("current_phase", "initial")
            complete = state.get("workflow_complete", False)
            done_agents = PHASE_TO_AGENTS.get(phase, [])

            with phase_box.container():
                st.subheader("Phase Progress")
                c1, c2, c3 = st.columns(3)
                with c1:
                    st.markdown("**Phase 1: Detection**")
                    for agent in ["validation", "detection"]:
                        icon = "✅" if agent in done_agents else "⏳"
                        st.caption(f"{icon} {agent.capitalize()} Agent")
                with c2:
                    st.markdown("**Phase 2: Diagnosis**")
                    for agent in ["diagnosis", "lineage"]:
                        icon = "✅" if agent in done_agents else "⏳"
                        st.caption(f"{icon} {agent.capitalize()} Agent")
                with c3:
                    st.markdown("**Phase 3: Remediation**")
                    for agent, label in [
                        ("business_impact", "Business Impact"),
                        ("repair", "Repair"),
                    ]:
                        icon = "✅" if agent in done_agents else "⏳"
                        st.caption(f"{icon} {label} Agent")

            sev = state.get("severity")
            if sev:
                severity_box.markdown(severity_badge(sev), unsafe_allow_html=True)

            if complete:
                st.session_state["poll_complete"] = True
                with result_box.container():
                    render_results(state)
            else:
                time.sleep(2)
                st.rerun()
        else:
            time.sleep(2)
            st.rerun()

    elif st.session_state.get("poll_complete") and active_id:
        state = api_get(f"/api/v1/investigations/{active_id}")
        if isinstance(state, dict) and "error" not in state:
            st.markdown(f"**Investigation:** `{active_id}`")
            render_results(state)
        if st.button("New Investigation"):
            st.session_state.pop("active_id", None)
            st.session_state.pop("poll_complete", None)
            st.rerun()

# ===========================================================================
# TAB 2 — Investigation History
# ===========================================================================

with tab2:
    st.header("Investigation History")

    data = api_get("/api/v1/investigations", params={"limit": 20})
    if isinstance(data, dict) and "error" in data:
        st.error(f"Could not load investigations: {data['error']}")
    elif not data:
        st.info("No investigations yet. Run one from the first tab.")
    else:
        rows = data if isinstance(data, list) else []
        st.dataframe(rows, use_container_width=True)

        st.subheader("Investigation Details")
        inv_ids = [r["investigation_id"] for r in rows]
        selected = st.selectbox("Select investigation", inv_ids)

        if selected:
            detail = api_get(f"/api/v1/investigations/{selected}")
            if isinstance(detail, dict) and "error" not in detail:
                with st.expander(f"Details: {selected}", expanded=True):
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.json(
                            {
                                k: v
                                for k, v in detail.items()
                                if k in ("current_phase", "severity", "trigger", "errors")
                            }
                        )
                    with col2:
                        if st.button("✅ Mark Resolved", key=f"resolve_{selected}"):
                            result = api_post(
                                f"/api/v1/investigations/{selected}/feedback",
                                {"was_resolved": True, "resolution_notes": ""},
                            )
                            if "error" not in result:
                                st.success(
                                    f"Marked resolved ({result.get('decisions_updated', 0)} decisions updated)"
                                )
                            else:
                                st.error(result["error"])
                        if st.button("❌ Mark Unresolved", key=f"unresolve_{selected}"):
                            result = api_post(
                                f"/api/v1/investigations/{selected}/feedback",
                                {"was_resolved": False, "resolution_notes": ""},
                            )
                            if "error" not in result:
                                st.success("Marked unresolved")
                            else:
                                st.error(result["error"])

# ===========================================================================
# TAB 3 — Knowledge Base
# ===========================================================================

with tab3:
    st.header("Knowledge Base Search")

    query = st.text_input("Query", placeholder="e.g. null spike in customer_id column")
    col1, col2 = st.columns([2, 1])
    with col1:
        collection = st.selectbox(
            "Collection",
            ["anomaly_patterns", "dq_rules", "remediation_playbooks", "business_context"],
        )
    with col2:
        k = st.slider("Results", min_value=1, max_value=10, value=3)

    if st.button("🔍 Search Knowledge Base", use_container_width=True):
        if not query:
            st.warning("Enter a query first.")
        else:
            resp = api_post(
                "/api/v1/rag/query", {"query": query, "collection": collection, "limit": k}
            )
            if "error" in resp:
                st.error(f"Search failed: {resp['error']}")
            else:
                results = resp.get("results", [])
                if not results:
                    st.info("No results found.")
                else:
                    st.success(f"{len(results)} result(s) found.")
                    for i, item in enumerate(results):
                        score = item.get("score", 1.0)
                        with st.expander(f"Result {i + 1} (score: {score:.3f})", expanded=i == 0):
                            st.markdown(item.get("content", ""))
                            st.json(item.get("metadata", {}))
