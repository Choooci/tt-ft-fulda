"""
Tischtennis-Team App
Zwei Ansichten: Spieler (Rückmeldung geben) und Mannschaftsführer (Verwaltung)
"""

import streamlit as st
from datetime import datetime, timedelta
from supabase import create_client
from icalendar import Calendar
import pandas as pd

# --- Passwort-Schutz ---
def check_password():
    """Returns `True` if the user had the correct password."""

    def password_entered():
        """Checks whether a password entered by the user is correct."""
        if st.session_state["password"] == st.secrets["APP_PASSWORD"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # Don't store password
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        # First run, show input for password.
        st.text_input(
            "Passwort eingeben", type="password", on_change=password_entered, key="password"
        )
        return False
    elif not st.session_state["password_correct"]:
        # Password not correct, show input + error.
        st.text_input(
            "Passwort eingeben", type="password", on_change=password_entered, key="password"
        )
        st.error("😕 Passwort falsch")
        return False
    else:
        # Password correct.
        return True

if not check_password():
    st.stop()

# --- Verbindung zu Supabase herstellen ---
supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

st.set_page_config(page_title="Tischtennis Team", page_icon="🏓", layout="wide")

# ============================================================
# HILFSFUNKTIONEN
# ============================================================

def hole_alle_spieler():
    """Holt alle Spieler aus der Datenbank."""
    return supabase.table("players").select("*").order("name").execute().data

def hole_alle_spiele():
    """Holt alle Spiele, sortiert nach Datum."""
    return supabase.table("matches").select("*").order("datum_aktuell").execute().data

def hole_anstehende_spiele(tage_voraus: int = 365):
    """Holt Spiele in den nächsten X Tagen (Standard: 1 Jahr, damit nichts fehlt)."""
    heute = datetime.now()
    grenze = heute + timedelta(days=tage_voraus)
    return supabase.table("matches") \
        .select("*") \
        .gte("datum_aktuell", heute.isoformat()) \
        .lte("datum_aktuell", grenze.isoformat()) \
        .eq("ist_abgesagt", False) \
        .order("datum_aktuell") \
        .execute().data

def hole_rueckmeldungen_fuer_spiel(match_id: int):
    """Holt alle Rückmeldungen zu einem bestimmten Spiel."""
    return supabase.table("availability") \
        .select("*, players(name)") \
        .eq("match_id", match_id) \
        .execute().data

def hole_offene_spiele_fuer_spieler(player_id: int, tage_voraus: int = 365):
    """Findet Spiele, zu denen der Spieler noch keine Rückmeldung gegeben hat."""
    spiele = hole_anstehende_spiele(tage_voraus)
    offene = []
    for spiel in spiele:
        vorhanden = supabase.table("availability") \
            .select("id") \
            .eq("match_id", spiel["id"]) \
            .eq("player_id", player_id) \
            .execute().data
        if not vorhanden:
            offene.append(spiel)
    return offene

def hole_rueckmeldung_fuer_spieler_und_spiel(player_id: int, match_id: int):
    """Holt die vorhandene Rückmeldung eines Spielers zu einem Spiel (falls vorhanden)."""
    ergebnis = supabase.table("availability") \
        .select("*") \
        .eq("match_id", match_id) \
        .eq("player_id", player_id) \
        .execute().data
    return ergebnis[0] if ergebnis else None

def speichere_rueckmeldung(player_id: int, match_id: int, kann_spielen, bringt_getraenke: bool, kommentar: str):
    """Speichert oder aktualisiert eine Rückmeldung (upsert)."""
    vorhanden = supabase.table("availability") \
        .select("id") \
        .eq("match_id", match_id) \
        .eq("player_id", player_id) \
        .execute().data

    daten = {
        "player_id": player_id,
        "match_id": match_id,
        "kann_spielen": kann_spielen,
        "bringt_getraenke": bringt_getraenke,
        "kommentar": kommentar
    }

    if vorhanden:
        supabase.table("availability").update(daten).eq("id", vorhanden[0]["id"]).execute()
    else:
        supabase.table("availability").insert(daten).execute()

def zaehle_zusagen(spiel):
    """Zählt alle Zusagen zu einem Spiel, inklusive Ersatzspieler."""
    rueckmeldungen = hole_rueckmeldungen_fuer_spiel(spiel["id"])
    zusagen = sum(1 for r in rueckmeldungen if r["kann_spielen"] is True)

    # Ersatzspieler zählen (als JSON Liste)
    if spiel.get("ersatz_spieler"):
        import json
        try:
            ersatz_liste = json.loads(spiel["ersatz_spieler"])
            zusagen += len([e for e in ersatz_liste if e.strip()])
        except:
            pass

    return zusagen

def loesche_gesamten_spielplan():
    """Löscht alle Spiele (und dank Cascade auch alle Rückmeldungen)."""
    supabase.table("matches").delete().neq("id", 0).execute()

def loesche_alle_rueckmeldungen():
    """Löscht nur die Rückmeldungen, Spielplan bleibt erhalten."""
    supabase.table("availability").delete().neq("id", 0).execute()

# ============================================================
# SPIELER-ANSICHT
# ============================================================

def spieler_ansicht():
    st.title("🏓 Rückmeldung für Spiele")

    alle_spieler = hole_alle_spieler()

    if not alle_spieler:
        st.warning("Noch keine Spieler eingetragen. Bitte den Mannschaftsführer kontaktieren.")
        return

    spieler_namen = [s["name"] for s in alle_spieler]
    ausgewaehlter_name = st.selectbox("Wer bist Du?", spieler_namen)
    ausgewaehlter_spieler = next(s for s in alle_spieler if s["name"] == ausgewaehlter_name)
    player_id = ausgewaehlter_spieler["id"]

    st.info(f"👤 Du trägst Deine Rückmeldungen gerade als **{ausgewaehlter_name}** ein.")

    spiele = hole_anstehende_spiele(tage_voraus=365)

    if not spiele:
        st.info("Aktuell sind keine Spiele eingetragen.")
        return

    # --- Vorhandene Rückmeldungen laden und in Session State packen ---
    if st.session_state.get("aktueller_spieler_id") != player_id:
        st.session_state["aktueller_spieler_id"] = player_id
        st.session_state["rueckmeldungen_entwurf"] = {}

        for spiel in spiele:
            vorhanden = hole_rueckmeldung_fuer_spieler_und_spiel(player_id, spiel["id"])
            if vorhanden:
                st.session_state["rueckmeldungen_entwurf"][spiel["id"]] = {
                    "kann_spielen": vorhanden["kann_spielen"],
                    "bringt_getraenke": vorhanden["bringt_getraenke"],
                    "kommentar": vorhanden.get("kommentar", "") or ""
                }
            else:
                st.session_state["rueckmeldungen_entwurf"][spiel["id"]] = {
                    "kann_spielen": None,
                    "bringt_getraenke": False,
                    "kommentar": ""
                }

    # --- Fortschrittsanzeige ---
    entwurf = st.session_state["rueckmeldungen_entwurf"]
    ausgefuellt = sum(1 for v in entwurf.values() if v["kann_spielen"] is not None)
    gesamt = len(spiele)

    st.progress(ausgefuellt / gesamt if gesamt > 0 else 0)
    if ausgefuellt == gesamt:
        st.success(f"✅ Du hast alle {gesamt} Spiele ausgefüllt!")
    else:
        st.warning(f"❓ Du musst noch abstimmen: {ausgefuellt} von {gesamt} Spielen ausgefüllt.")

    st.info(
        "**So funktioniert's:** Trage bei jedem Spiel ein, ob Du kannst, und ob Du Getränke mitbringst. "
        "Deine Eingaben werden erst gespeichert, wenn Du unten auf **'Alle Rückmeldungen speichern'** klickst."
    )

    st.divider()

    # --- Für jedes Spiel Eingabefelder anzeigen ---
    for spiel in spiele:
        datum = datetime.fromisoformat(spiel["datum_aktuell"]).strftime("%d.%m.%Y (%H:%M Uhr)")
        gegner = spiel.get("gegner", "Unbekannt")

        aktuelle_werte = entwurf[spiel["id"]]

        status_icon = "✅" if aktuelle_werte["kann_spielen"] is True else "❌" if aktuelle_werte["kann_spielen"] is False else "❓"

        with st.expander(f"{status_icon} {datum} – {gegner}"):
            st.write(f"**Rückmeldung von: {ausgewaehlter_name}**")

            if spiel.get("ist_verlegt"):
                st.caption(f"⚠ Verlegt von: {spiel['datum_original']}")
            if spiel.get("ort"):
                st.caption(f"📍 Ort: {spiel['ort']}")

            kann_optionen = ["Weiß noch nicht", "Ja, ich kann", "Nein, ich kann nicht"]
            aktueller_wert = aktuelle_werte["kann_spielen"]
            if aktueller_wert is True:
                index = 1
            elif aktueller_wert is False:
                index = 2
            else:
                index = 0

            auswahl = st.radio(
                "Kannst Du spielen?",
                kann_optionen,
                index=index,
                key=f"kann_{player_id}_{spiel['id']}"
            )

            getraenke = st.checkbox(
                "🍺 Ich bringe Bier/Getränke mit",
                value=aktuelle_werte["bringt_getraenke"],
                key=f"getraenke_{player_id}_{spiel['id']}"
            )

            kommentar = st.text_input(
                "Kommentar (optional)",
                value=aktuelle_werte["kommentar"],
                key=f"kommentar_{player_id}_{spiel['id']}"
            )

            # Entwurf im Session State aktualisieren
            if auswahl == "Ja, ich kann":
                kann_spielen_wert = True
            elif auswahl == "Nein, ich kann nicht":
                kann_spielen_wert = False
            else:
                kann_spielen_wert = None

            st.session_state["rueckmeldungen_entwurf"][spiel["id"]] = {
                "kann_spielen": kann_spielen_wert,
                "bringt_getraenke": getraenke,
                "kommentar": kommentar
            }

    st.divider()

    if st.button("💾 Alle Rückmeldungen speichern", type="primary", use_container_width=True):
        for spiel_id, werte in st.session_state["rueckmeldungen_entwurf"].items():
            speichere_rueckmeldung(
                player_id,
                spiel_id,
                werte["kann_spielen"],
                werte["bringt_getraenke"],
                werte["kommentar"]
            )
        st.success("✅ Alle Rückmeldungen wurden gespeichert!")
        st.rerun()

# ============================================================
# MANNSCHAFTSFÜHRER-ANSICHT
# ============================================================

def tab_uebersicht():
    st.subheader("Alle anstehenden Spiele")

    st.info(
        "**So funktioniert diese Übersicht:**\n\n"
        "- 🟢 Grün = mindestens 4 Zusagen (inkl. Ersatzspieler), alles gut\n"
        "- 🟡 Gelb = genau 3 Zusagen, im Blick behalten\n"
        "- 🔴 Rot = 2 oder weniger Zusagen, Ersatz suchen oder Termin verlegen nötig\n\n"
        "Klicke ein Spiel auf, um alle Rückmeldungen im Detail zu sehen und Ersatzspieler einzutragen."
    )

    spiele = hole_anstehende_spiele(tage_voraus=365)
    alle_spieler = hole_alle_spieler()

    if not spiele:
        st.info("Keine anstehenden Spiele gefunden. Lade zuerst eine ICS-Datei hoch (Tab ganz rechts).")
        return

    for spiel in spiele:
        datum = datetime.fromisoformat(spiel["datum_aktuell"]).strftime("%d.%m.%Y (%H:%M Uhr)")
        gegner = spiel.get("gegner", "Unbekannt")
        zusagen = zaehle_zusagen(spiel)
        rueckmeldungen = hole_rueckmeldungen_fuer_spiel(spiel["id"])

        if zusagen <= 2:
            farbe = "🔴"
        elif zusagen == 3:
            farbe = "🟡"
        else:
            farbe = "🟢"

        with st.expander(f"{farbe} {datum} – {gegner} ({zusagen} Zusagen)"):
            if spiel.get("ist_verlegt"):
                st.info(f"⚠ Verlegt von: {spiel['datum_original']}")

            if spiel.get("ort"):
                st.write(f"**Ort:** {spiel['ort']}")

            st.divider()
            st.write("**Rückmeldungen:**")

            if rueckmeldungen:
                for r in rueckmeldungen:
                    name = r["players"]["name"]
                    if r["kann_spielen"] is True:
                        kann = "✅"
                    elif r["kann_spielen"] is False:
                        kann = "❌"
                    else:
                        kann = "❓"
                    getraenke = "🍺" if r["bringt_getraenke"] else ""
                    kommentar = f" – _{r['kommentar']}_" if r.get("kommentar") else ""
                    st.write(f"{kann} {name} {getraenke}{kommentar}")
            else:
                st.write("_Noch keine Rückmeldungen_")

            # Ersatzspieler anzeigen
            import json
            ersatz_liste = []
            if spiel.get("ersatz_spieler"):
                try:
                    ersatz_liste = json.loads(spiel["ersatz_spieler"])
                    ersatz_liste = [e for e in ersatz_liste if e.strip()]
                except:
                    ersatz_liste = []

            if ersatz_liste:
                st.divider()
                st.write("**Ersatzspieler:**")
                for ersatz in ersatz_liste:
                    st.write(f"👤 {ersatz}")

            st.divider()
            st.write("**Ersatzspieler verwalten**")

            col1, col2 = st.columns([4, 1])

            with col1:
                neuer_ersatz = st.text_input(
                    "Ersatzspieler hinzufügen",
                    value="",
                    key=f"ersatz_input_{spiel['id']}",
                    label_visibility="collapsed"
                )

            with col2:
                if st.button("➕ Hinzufügen", key=f"ersatz_add_{spiel['id']}"):
                    if neuer_ersatz.strip():
                        ersatz_liste.append(neuer_ersatz.strip())
                        supabase.table("matches").update({
                            "ersatz_spieler": json.dumps(ersatz_liste)
                        }).eq("id", spiel["id"]).execute()
                        st.success("Ersatzspieler hinzugefügt!")
                        st.rerun()

            if ersatz_liste:
                st.write("**Entfernen:**")
                for idx, ersatz in enumerate(ersatz_liste):
                    col1, col2 = st.columns([4, 1])
                    with col1:
                        st.write(f"👤 {ersatz}")
                    with col2:
                        if st.button("🗑", key=f"ersatz_del_{spiel['id']}_{idx}"):
                            ersatz_liste.pop(idx)
                            supabase.table("matches").update({
                                "ersatz_spieler": json.dumps(ersatz_liste)
                            }).eq("id", spiel["id"]).execute()
                            st.success("Ersatzspieler entfernt!")
                            st.rerun()

            if zusagen <= 2:
                st.error(f"⚠ Nur {zusagen} Zusagen! Ersatz suchen oder verlegen nötig.")
            elif zusagen == 3:
                st.warning(f"⚠ Erst {zusagen} Zusagen. Im Blick behalten.")

def tab_spiel_bearbeiten():
    st.subheader("Spiel verlegen oder absagen")

    alle_spiele = hole_alle_spiele()
    if not alle_spiele:
        st.info("Keine Spiele vorhanden. Lade zuerst eine ICS-Datei hoch (Tab ganz rechts).")
        return

    spiel_optionen = {
        f"{datetime.fromisoformat(s['datum_aktuell']).strftime('%d.%m.%Y')} – {s.get('gegner', 'Unbekannt')}": s
        for s in alle_spiele
    }
    ausgewaehlt = st.selectbox("Spiel auswählen", list(spiel_optionen.keys()))
    spiel = spiel_optionen[ausgewaehlt]

    st.divider()

    neues_datum = st.date_input(
        "Neues Datum (falls verlegt)",
        value=datetime.fromisoformat(spiel["datum_aktuell"]).date()
    )
    neue_zeit = st.time_input(
        "Neue Uhrzeit",
        value=datetime.fromisoformat(spiel["datum_aktuell"]).time()
    )

    ist_abgesagt = st.checkbox("Spiel komplett abgesagt", value=spiel.get("ist_abgesagt", False))

    if st.button("Änderungen speichern", type="primary"):
        neues_datetime = datetime.combine(neues_datum, neue_zeit)
        wurde_verlegt = neues_datetime.isoformat() != spiel["datum_aktuell"]

        supabase.table("matches").update({
            "datum_aktuell": neues_datetime.isoformat(),
            "ist_verlegt": wurde_verlegt or spiel.get("ist_verlegt", False),
            "ist_abgesagt": ist_abgesagt
        }).eq("id", spiel["id"]).execute()

        st.success("Änderungen gespeichert!")
        st.rerun()

    st.divider()
    st.subheader("⚠ Gefahrenzone")

    with st.expander("Spielplan oder Rückmeldungen löschen"):
        st.warning("Diese Aktionen können nicht rückgängig gemacht werden!")

        col1, col2 = st.columns(2)

        with col1:
            st.write("**Gesamten Spielplan löschen**")
            st.caption("Löscht alle Spiele UND alle Rückmeldungen.")
            bestaetigung_spielplan = st.checkbox("Ich bin sicher, dass ich den gesamten Spielplan löschen möchte.", key="best_spielplan")
            if st.button("🗑 Spielplan löschen", disabled=not bestaetigung_spielplan):
                loesche_gesamten_spielplan()
                st.success("Spielplan wurde gelöscht.")
                st.rerun()

        with col2:
            st.write("**Nur Rückmeldungen löschen**")
            st.caption("Spielplan bleibt erhalten, alle Rückmeldungen werden zurückgesetzt.")
            bestaetigung_rueckmeldungen = st.checkbox("Ich bin sicher, dass ich alle Rückmeldungen löschen möchte.", key="best_rueckmeldungen")
            if st.button("🗑 Rückmeldungen löschen", disabled=not bestaetigung_rueckmeldungen):
                loesche_alle_rueckmeldungen()
                st.success("Alle Rückmeldungen wurden gelöscht.")
                st.rerun()

def tab_spieler_verwalten():
    st.subheader("Spieler im Team eintragen")

    st.info(
        "**So funktioniert's:** Trage hier alle Spieler ein, die im Team mitspielen. "
        "Jeder Spieler kann sich später in der Spieler-Ansicht per Namensauswahl für Spiele zurückmelden."
    )

    alle_spieler = hole_alle_spieler()

    st.write("**Aktuelle Spieler:**")
    if alle_spieler:
        for s in alle_spieler:
            col1, col2 = st.columns([4, 1])
            with col1:
                st.write(f"👤 {s['name']}")
            with col2:
                if st.button("Entfernen", key=f"entfernen_{s['id']}"):
                    supabase.table("players").delete().eq("id", s["id"]).execute()
                    st.rerun()
    else:
        st.write("_Noch keine Spieler eingetragen_")

    st.divider()

    with st.form("neuer_spieler_form"):
        neuer_name = st.text_input("Name des neuen Spielers")
        abschicken = st.form_submit_button("Spieler hinzufügen")

        if abschicken and neuer_name.strip():
            supabase.table("players").insert({"name": neuer_name.strip()}).execute()
            st.success(f"{neuer_name} wurde hinzugefügt!")
            st.rerun()

def tab_ics_import():
    st.subheader("ICS-Datei hochladen")

    st.info(
        "**So funktioniert's:**\n\n"
        "1. Lade zu Saisonbeginn die ICS-Datei Deines Spielplans hoch (bekommst Du meist vom Verband/Verein)\n"
        "2. Alle Spiele werden automatisch eingelesen und erscheinen in der Übersicht\n"
        "3. Falls Du die Datei später erneut hochlädst, werden nur neue Spiele hinzugefügt, keine doppelten Einträge"
    )

    hochgeladene_datei = st.file_uploader("ICS-Datei auswählen", type=["ics"])

    if hochgeladene_datei is not None:
        if st.button("Spielplan importieren", type="primary"):
            inhalt = hochgeladene_datei.read()
            kalender = Calendar.from_ical(inhalt)

            importierte_anzahl = 0
            uebersprungen_anzahl = 0

            for komponente in kalender.walk():
                if komponente.name == "VEVENT":
                    start = komponente.get("dtstart").dt
                    if isinstance(start, datetime):
                        datum_iso = start.isoformat()
                    else:
                        datum_iso = datetime.combine(start, datetime.min.time()).isoformat()

                    zusammenfassung = str(komponente.get("summary", "Unbekannt"))
                    ort = str(komponente.get("location", ""))

                    # Prüfen, ob dieses Spiel schon existiert (gleiches Datum + gleicher Gegner)
                    vorhanden = supabase.table("matches") \
                        .select("id") \
                        .eq("datum_original", datum_iso) \
                        .eq("gegner", zusammenfassung) \
                        .execute().data

                    if vorhanden:
                        uebersprungen_anzahl += 1
                        continue

                    supabase.table("matches").insert({
                        "datum_original": datum_iso,
                        "datum_aktuell": datum_iso,
                        "gegner": zusammenfassung,
                        "ort": ort,
                        "ist_verlegt": False,
                        "ist_abgesagt": False,
                        "ersatz_spieler": "[]"
                    }).execute()
                    importierte_anzahl += 1

            st.success(f"✅ {importierte_anzahl} neue Spiele importiert. {uebersprungen_anzahl} bereits vorhandene Spiele übersprungen.")
            st.rerun()

def mannschaftsfuehrer_ansicht():
    st.title("🏓 Dashboard – Mannschaftsführer")

    tab1, tab2, tab3, tab4 = st.tabs([
        "📅 Übersicht",
        "✏ Spiel bearbeiten",
        "👥 Spieler verwalten",
        "📤 ICS Import"
    ])

    with tab1:
        tab_uebersicht()

    with tab2:
        tab_spiel_bearbeiten()

    with tab3:
        tab_spieler_verwalten()

    with tab4:
        tab_ics_import()

# ============================================================
# HAUPTNAVIGATION
# ============================================================

def main():
    st.sidebar.title("🏓 Navigation")
    ansicht = st.sidebar.radio("Ansicht wählen", ["Spieler", "Mannschaftsführer"])

    if ansicht == "Spieler":
        spieler_ansicht()
    else:
        mannschaftsfuehrer_ansicht()

if __name__ == "__main__":
    main()
