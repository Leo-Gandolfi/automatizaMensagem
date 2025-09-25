# -*- coding: utf-8 -*-
import re
import time
import io
import base64
import unicodedata
import requests
import pandas as pd
import streamlit as st
from streamlit.components.v1 import html

TOKEN = "xxxx"
PHONE_NUMBER_ID = "xx"
GRAPH_VERSION = "v22.0"

st.set_page_config(page_title="Envio WhatsApp por Planilha", layout="wide")

st.markdown(
    """
    <style>
      :root { --primary:#003087; --accent:#EC6608; --bg:#FFFFFF; --text:#0B0B0B; --muted:#6B7280; }
      .stApp { background: var(--bg); color: var(--text); }
      [data-testid="stSidebar"] { background: #062a6a; padding-top: 12px; }
      [data-testid="stSidebar"] * { color: #ffffff !important; }
      .stButton>button { background: var(--accent) !important; color:#fff !important; border:0; border-radius:10px; padding:.7rem 1.1rem; font-weight:700; letter-spacing:.2px; }
      .stDownloadButton>button { background:#fff !important; color:var(--primary) !important; border:2px solid var(--primary); border-radius:10px; padding:.6rem 1rem; font-weight:700; }
      .wrapper { max-width: 1100px; margin: 0 auto; padding: 6px 8px 40px 8px; }
      .h1 { font-size: 28px; font-weight: 800; color: var(--primary); margin: 8px 0 2px 0; }
      .subtitle { color: var(--muted); margin-bottom: 18px; }
      .metric { background:#fff; border:1px solid #E7ECF5; border-radius:14px; padding:14px 16px; text-align:center; }
      .metric b { display:block; color:var(--muted); font-size:12px; margin-bottom:6px; }
      .section-title { font-weight:800; color:#1F2937; margin:8px 0 8px 0; font-size:18px; }
      div[role="alert"] { color:#842029 !important; }
      .st-emotion-cache-ue6h4q p, .st-emotion-cache-ue6h4q h4 { margin: 0; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.sidebar.markdown("### Configurações")
template_name = st.sidebar.text_input("Nome do template", value="modelo_retorno_vaga_1")
template_lang  = st.sidebar.text_input("Idioma do template", value="pt_BR")
sleep_between  = st.sidebar.number_input("Intervalo entre envios (s)", 0.0, 5.0, 0.2, 0.1)
dry_run        = st.sidebar.checkbox("Dry run (não envia, só simula)", value=False)

st.markdown('<div class="wrapper">', unsafe_allow_html=True)
st.markdown('<div class="h1">Envio WhatsApp por Planilha</div>', unsafe_allow_html=True)
st.markdown('<div class="subtitle">Faça upload do arquivo, revise os destinatários e dispare o modelo.</div>', unsafe_allow_html=True)

def only_digits(s: str) -> str:
    return "".join(ch for ch in str(s) if ch.isdigit())

def ensure_br_prefix(number: str) -> str:
    d = only_digits(number)
    if not d.startswith("55"):
        d = "55" + d
    return d

def send_template(to: str):
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "to": to, "type": "template",
               "template": {"name": template_name, "language": {"code": template_lang}}}
    return requests.post(url, headers=headers, json=payload, timeout=30)

def norm_label(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[\s\-\–\—_]+", " ", s.strip().lower())
    s = re.sub(r"[^a-z0-9 ]+", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

expected_labels = {
    norm_label("Requisição - ID da Requisição"): "id da requisição",
    norm_label("Campos Calculados - Nome do Candidato"): "nome do candidato",
    norm_label("Requisição - Responsável pela Requisição - Nome"): "nome do responsável",
    norm_label("Usuário - Usuário Candidato - Número do Telefone do Usuário"): "telefone",
    norm_label("Detalhes do Candidato - Status Atual do Candidato"): "status",
}

def try_read_table(uploaded_file):
    name = uploaded_file.name.lower()
    data = uploaded_file.read()
    uploaded_file.seek(0)
    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(data), header=None, dtype=str)
    for enc in ("utf-8-sig", "utf-8", "latin1", "cp1252"):
        try:
            txt = data.decode(enc, errors="replace")
            try:
                df = pd.read_csv(io.StringIO(txt), header=None, dtype=str, sep=None, engine="python")
            except Exception:
                best = None; best_count = -1
                for sep in [",",";","|","\t"]:
                    try:
                        t = pd.read_csv(io.StringIO(txt), header=None, dtype=str, sep=sep)
                        mc = t.shape[1]
                        if mc > best_count:
                            best = t; best_count = mc
                    except Exception:
                        pass
                df = best if best is not None else pd.read_csv(io.StringIO(txt), header=None, dtype=str)
            return df
        except Exception:
            continue
    return pd.read_csv(io.BytesIO(data), header=None, dtype=str, sep=None, engine="python")

def detect_header_and_columns(df_try):
    header_row = None
    for i in range(min(50, len(df_try))):
        row_vals = [str(x) for x in list(df_try.iloc[i].fillna(""))]
        row_norm = [norm_label(x) for x in row_vals]
        match_count = sum(1 for lbl in expected_labels.keys() if lbl in row_norm)
        if match_count >= 3:
            header_row = i
            break
    if header_row is None:
        return None, None
    df = df_try.copy()
    df.columns = df.iloc[header_row].fillna("").tolist()
    df = df.iloc[header_row + 1 :].reset_index(drop=True)
    col_map = {}
    for col in df.columns:
        k = norm_label(col)
        if k in expected_labels and expected_labels[k] not in col_map.values():
            col_map[col] = expected_labels[k]
    return df, col_map

st.markdown('<div class="section-title">1) Upload do arquivo</div>', unsafe_allow_html=True)
file = st.file_uploader("Carregar CSV ou Excel", type=["csv", "xlsx", "xls"], label_visibility="collapsed", key="up")

if file is not None:
    df_try = try_read_table(file)
    df, col_map = detect_header_and_columns(df_try)
    if df is None or not col_map:
        st.error("Não foi possível identificar o cabeçalho e as colunas. Verifique o arquivo ou envie um exemplo.")
        st.stop()

    view = df[list(col_map.keys())].rename(columns=col_map).copy()
    if "mensagem" not in view.columns:
        view["mensagem"] = ""
    view["telefone"] = view["telefone"].astype(str).apply(ensure_br_prefix)
    view["selecionado"] = True

    st.markdown('<div class="section-title">2) Candidatos</div>', unsafe_allow_html=True)
    select_all = st.checkbox("Selecionar todos", value=True)
    if not select_all:
        view["selecionado"] = False

    cols_show = ["selecionado","id da requisição","nome do candidato","nome do responsável","telefone","status","mensagem"]
    edited = st.data_editor(
        view[cols_show],
        use_container_width=True,
        hide_index=True,
        column_config={
            "selecionado": st.column_config.CheckboxColumn("Selecionado"),
            "id da requisição": st.column_config.TextColumn("ID da Requisição"),
            "nome do candidato": st.column_config.TextColumn("Nome do Candidato"),
            "nome do responsável": st.column_config.TextColumn("Nome do Responsável"),
            "telefone": st.column_config.TextColumn("Telefone"),
            "status": st.column_config.TextColumn("Status"),
            "mensagem": st.column_config.TextColumn("Mensagem", width="medium", help="Campo livre para observações"),
        },
    )

    total = len(edited)
    sel = int(edited["selecionado"].sum())
    c1, c2 = st.columns(2)
    with c1: st.markdown(f'<div class="metric"><b>Total de linhas</b><span style="font-size:22px;font-weight:800">{total}</span></div>', unsafe_allow_html=True)
    with c2: st.markdown(f'<div class="metric"><b>Selecionadas</b><span style="font-size:22px;font-weight:800">{sel}</span></div>', unsafe_allow_html=True)

    st.markdown('<div class="section-title">3) Disparo</div>', unsafe_allow_html=True)
    if st.button("Enviar agora"):
        sending = edited[edited["selecionado"] == True].copy()
        if sending.empty:
            st.warning("Nenhuma linha selecionada.")
            st.stop()

        results = []
        progress = st.progress(0)
        log_area = st.empty()

        for pos, (_, row) in enumerate(sending.iterrows(), start=1):
            to = only_digits(row["telefone"])
            if not to or len(to) < 12:
                results.append({"index": row.name, "status_envio": "erro: telefone inválido"})
                progress.progress(int(pos * 100 / max(1, len(sending))))
                continue
            to = ensure_br_prefix(to)

            if dry_run:
                results.append({"index": row.name, "status_envio": "simulado"})
            else:
                try:
                    r = send_template(to)
                    msg = "enviado" if 200 <= r.status_code < 300 else f"erro {r.status_code}"
                    try:
                        j = r.json()
                        det = j.get("error", {}).get("error_data", {}).get("details")
                        if det and "erro" in msg:
                            msg = f"{msg}: {det}"
                    except Exception:
                        pass
                    results.append({"index": row.name, "status_envio": msg})
                except Exception as e:
                    results.append({"index": row.name, "status_envio": f"erro: {e}"})

            log_area.write(f"Processando {pos}/{len(sending)}")
            progress.progress(int(pos * 100 / max(1, len(sending))))
            time.sleep(float(sleep_between))

        out = edited.copy()
        out["status_envio"] = ""
        res = pd.DataFrame(results).set_index("index")
        for i, r in res.iterrows():
            out.loc[i, "status_envio"] = r["status_envio"]

        out = out[["id da requisição","nome do candidato","nome do responsável","telefone","status","status_envio"]]

        st.markdown('<div class="section-title">4) Resultado</div>', unsafe_allow_html=True)
        st.dataframe(out, use_container_width=True, hide_index=True)

        xbuf = io.BytesIO()
        with pd.ExcelWriter(xbuf, engine="xlsxwriter") as writer:
            sheet = "Envios"
            out.to_excel(writer, index=False, sheet_name=sheet)
            wb  = writer.book
            ws  = writer.sheets[sheet]
            header_fmt = wb.add_format({"bold": True, "bg_color": "#003087", "font_color": "#FFFFFF"})
            for col_idx, col_name in enumerate(out.columns):
                ws.write(0, col_idx, col_name, header_fmt)
                max_len = max(12, min(60, int(out[col_name].astype(str).map(len).max() or 0) + 2))
                ws.set_column(col_idx, col_idx, max_len)
            ws.freeze_panes(1, 0)

        data_bytes = xbuf.getvalue()
        filename = f"resultado_envio_{int(time.time())}.xlsx"

        b64 = base64.b64encode(data_bytes).decode()
        auto_dl = f"""
        <html>
        <body>
          <a id="dl" download="{filename}"
             href="data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{b64}"></a>
          <script>
            const a = document.getElementById('dl');
            if (a) a.click();
          </script>
        </body>
        </html>
        """
        html(auto_dl, height=0)
        st.success("Relatório gerado e download iniciado automaticamente.")
        st.download_button(
            "Baixar Excel (caso o download automático não inicie)",
            data=data_bytes,
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

st.markdown("</div>", unsafe_allow_html=True)
