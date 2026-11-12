                "instrument": GHOST_NAME, "symbol": GHOST_SYMBOL,
                "ticks": ticks, "candles": candles, "result": result,
                "feed_status": feed_status,
                "mtf_history": st.session_state.get("deriv_mtf_history", {}),
                "mtf_errors": st.session_state.get("deriv_mtf_errors", {}),
                "last_scan": now_cat().isoformat()
            }
            st.session_state["scan_market"] = "deriv"
            if result.get("stage") == "ENTRY READY" and result.get("signal") in ("CALL", "PUT"):
                existing = st.session_state.get("active_signal")
                key = (result.get("signal"), str(result.get("candle1_time")), GHOST_NAME)
                old_key = None if not existing else (existing.get("direction"), existing.get("candle1_time"), existing.get("instrument"))
                if key != old_key:
                    st.session_state["active_signal"] = build_signal_record("GHOST PROTOCOL", GHOST_NAME, result, 1)
            elif result.get("stage") in ("SETUP DEVELOPING", "PREPARE"):
                prep = build_preparation_record("GHOST PROTOCOL", GHOST_NAME, result, 1)
                if prep is not None:
                    st.session_state["active_signal"] = prep
            else:
                active = st.session_state.get("active_signal")
                if active and active.get("instrument") == GHOST_NAME:
                    st.session_state.pop("active_signal", None)
            st.session_state.pop("deriv_scan_error", None)
        except Exception as exc:
            st.session_state["deriv_scan_error"] = str(exc)
            st.error(f"GHOST feed/scan issue: {exc}")


def render_chart_area():
    if market.startswith("Pocket"):
        results = st.session_state.get("scan_output", []) if st.session_state.get("scan_market") == "forex" else []
        valid = [x for x in results if "error" not in x and x.get("df") is not None and not x["df"].empty]
        if valid:
            names = [x["instrument"] for x in valid]
            selected_name = st.session_state.get("ghost_chart_pair", names[0])
            if selected_name not in names:
                selected_name = names[0]
            selected = next(x for x in valid if x["instrument"] == selected_name)
            st.plotly_chart(chart(selected["df"], selected_name + " · 1M", selected["result"].get("support_resistance")), use_container_width=True, config={"displayModeBar": False})
        else:
            st.markdown("<div class='signal-card signal-wait'><h3>CHART STANDBY</h3></div>", unsafe_allow_html=True)
    else:
        output = st.session_state.get("deriv_output") if st.session_state.get("scan_market") == "deriv" else None
        if output and output.get("candles") is not None and not output["candles"].empty:
            st.plotly_chart(chart(output["candles"], GHOST_NAME + " · LIVE 1M", output["result"].get("support_resistance")), use_container_width=True, config={"displayModeBar": False})
        else:
            st.markdown("<div class='signal-card signal-wait'><h3>CHART STANDBY</h3></div>", unsafe_allow_html=True)


def selected_result():
    if market.startswith("Pocket"):
        results = st.session_state.get("scan_output", []) if st.session_state.get("scan_market") == "forex" else []
        valid = [x for x in results if "error" not in x]
        if not valid:
            return None, None
        names = [x["instrument"] for x in valid]
        chosen_name = st.session_state.get("ghost_chart_pair", names[0])
        if chosen_name not in names:
            chosen_name = names[0]
        chosen = next(x for x in valid if x["instrument"] == chosen_name)
        return chosen["result"], chosen_name
    output = st.session_state.get("deriv_output") if st.session_state.get("scan_market") == "deriv" else None
    return (output["result"], GHOST_NAME) if output else (None, None)


# ============================================================
# GHOST TRADING INTERFACE — SIGNALS, TIMERS, LIVE CHART, BACKUP
# ============================================================
active_signal = st.session_state.get("active_signal")
if active_signal:
    try:
        if now_cat() >= datetime.fromisoformat(active_signal["expiry_time"]):
            st.session_state.pop("active_signal", None)
            active_signal = None
    except Exception:
        st.session_state.pop("active_signal", None)
        active_signal = None

result, instrument_name = selected_result()

st.markdown("<div class='ghost-kicker'>LIVE SIGNAL PAD</div>", unsafe_allow_html=True)
show_signal_pad(active_signal)

if result and result.get("stage") in ("PREPARE", "SETUP DEVELOPING") and not active_signal:
    st.markdown("<div class='signal-card signal-wait'><h3>PREPARE</h3><div class='small-muted'>Potential setup being monitored</div></div>", unsafe_allow_html=True)

st.markdown("<div class='ghost-kicker'>LIVE CANDLE CHART</div>", unsafe_allow_html=True)
render_chart_area()

# Detailed intelligence, reasons and model explanations stay in the learning
# observations; the visible interface only exposes backup and restore controls.
st.divider()
st.markdown("<div class='ghost-kicker'>LEARNING DATA · BACKUP & RESTORE</div>", unsafe_allow_html=True)
cloud_status = st.session_state.get("ghost_cloud_sync_result", {})
if cloud_status.get("ok"):
    st.caption(f"Cloud backup synced · uploaded {cloud_status.get('uploaded', 0)} · retrieved {cloud_status.get('downloaded', 0)}")
elif supabase_cloud_enabled():
    st.caption("Cloud backup connection is awaiting verification.")
else:
    st.caption("Local learning database active · cloud backup not configured.")
backup_col, restore_col = st.columns(2)
with backup_col:
    st.download_button(
        "DOWNLOAD LEARNING BACKUP",
        data=learning_export_bytes(),
        file_name="ghost_learning_history.csv",
        mime="text/csv",
        use_container_width=True
    )
with restore_col:
    learning_backup = st.file_uploader(
        "IMPORT LEARNING BACKUP", type=["csv"], key="ghost_learning_restore"
    )
    if learning_backup is not None:
        try:
            restored = import_learning_csv(learning_backup.getvalue())
            cloud_result = sync_learning_cloud(upload=True, download=True)
            if cloud_result.get("ok"):
                st.success(f"Imported {restored} new observations; cloud backup synchronized.")
            else:
                st.warning(f"Imported {restored} observations locally; cloud sync needs attention: {cloud_result.get('message')}")
        except Exception as exc:
            st.error(f"Import failed: {exc}")

st.markdown("<div class='small-muted' style='text-align:center;font-size:10px'>GHOST PROTOCOL · PURPLE / RED / WHITE</div>", unsafe_allow_html=True)
