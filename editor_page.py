# -*- coding: utf-8 -*-
"""초안 수정용 위지윅 에디터 페이지 (CKEditor 4).

QWebEngineView 에 띄울 HTML 을 만들어 줍니다.

■ 왜 CKEditor 5 가 아니라 4 인가
초안은 [[H]]·[[IMG:…]]·<blue> 같은 자체 문법이고, 이를 HTML 로 바꿔 편집한 뒤
그대로 되돌려야 합니다. CKEditor 5 는 자기 데이터 모델에 없는 태그·속성을 조용히
버리는데, CDN classic 빌드에는 이를 막아줄 GeneralHtmlSupport 도, 이 글에 꼭 필요한
FontColor·HorizontalLine 도 들어 있지 않습니다(실측 확인).
전체 기능이 든 super-build 는 유료 협업 플러그인이 의존성으로 얽혀 제거가 안 됩니다.
CKEditor 4 는 allowedContent:true 로 HTML 을 원형 그대로 보존하고 색상·구분선 버튼도
기본 제공해서, 실제 초안으로 왕복 검사했을 때 153줄이 한 글자도 틀리지 않았습니다.

CDN 을 못 받아오면 브라우저 기본 contenteditable 로 자동 전환해서
오프라인에서도 편집 자체는 계속 되도록 했습니다.

파이썬 ↔ 페이지:
  · 파이썬 → 페이지 :  setContent(html) / getContent() 를 runJavaScript 로 호출
  · 페이지 → 파이썬 :  window.__ready(준비됨), window.__dirty(수정됨)
"""
from __future__ import annotations

import json

import config

CKEDITOR_URL = "https://cdn.ckeditor.com/4.22.1/full/ckeditor.js"


# 편집 영역 '안쪽'에 들어갈 CSS.
# CKEditor 4 는 편집 영역을 iframe 으로 만들기 때문에 바깥 페이지의 <style> 이
# 닿지 않습니다. 그래서 이 CSS 는 contentsCss 로 따로 넣어줘야 하고,
# 대체 편집기(contenteditable)일 때는 바깥 페이지에도 같이 넣습니다.
CONTENT_CSS = f"""
  body {{
    background: #ffffff;
    line-height: 1.9;
    font-size: 15px;
    color: #1b1f27;
    text-align: center;
    padding: 18px 22px;
    margin: 0;
    font-family: "Malgun Gothic", "Segoe UI", sans-serif;
    word-break: break-all;
  }}
  h3, h3.dsl-h {{ font-size: 19px; font-weight: 700; margin: 22px 0 10px; color: #1b1f27; }}
  hr, hr.dsl-hr {{ border: none; border-top: 1px solid #d8dee7; margin: 20px 0; }}
  blockquote, blockquote.dsl-quote {{
    margin: 16px 0; padding: 10px 16px;
    border-left: 3px solid {config.COLOR_KEY};
    color: #5c6675; text-align: left;
  }}
  p {{ margin: 0 0 2px; }}
  p.blank {{ min-height: 1em; }}

  /* 이미지 블록 — 통째로 하나의 덩어리 */
  p.imgblock {{
    margin: 14px 0; padding: 8px;
    background: #f7f9fc; border: 1px dashed #c9d4e3; border-radius: 8px;
    display: flex; gap: 8px; justify-content: center; align-items: flex-start;
    max-width: 100%; overflow: hidden;
  }}
  p.imgblock .cell {{
    display: flex; flex-direction: column; align-items: center; gap: 4px;
    max-width: 50%;
  }}
  p.imgblock img {{
    max-width: 240px; max-height: 180px;
    width: auto; height: auto; object-fit: contain;
    border-radius: 4px; border: 1px solid #e3e8ef;
  }}
  p.imgblock.multi img {{ max-width: 175px; max-height: 150px; }}
  p.imgblock .cap {{ font-size: 11px; color: #8b94a3; }}
  p.imgblock .missing {{
    display: inline-block; padding: 20px 14px;
    background: #fbe6e5; color: #a5342d; border-radius: 4px; font-size: 12px;
  }}
"""

# 위 CSS 를 JS 문자열 리터럴로 (iframe 안에 <style> 로 직접 넣기 위해).
# contentsCss 에 data: URI 를 주는 방법은 iframe 에서 로드되지 않아 쓰지 않습니다.
_CONTENT_CSS_JS = json.dumps(CONTENT_CSS)


def build(inner_html: str = "") -> str:
    """에디터 페이지 전체 HTML."""
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<style>
  html, body {{
    margin: 0; padding: 0;
    background: #f4f6f9;
    font-family: "Malgun Gothic", "Segoe UI", sans-serif;
  }}
  #wrap {{ padding: 8px 10px 12px; }}
  #note {{ font-size: 12px; color: #8b94a3; padding: 6px 2px 0; }}
  #fallback {{
    min-height: 420px;
    border: 1px solid #d8dee7; border-radius: 6px;
    outline: none; overflow-y: auto;
  }}
  /* 대체 편집기(contenteditable)용 — CKEditor 는 iframe 안에 따로 주입합니다.
     본문 CSS 의 'body' 선택자만 '#fallback' 으로 바꿔 그대로 재사용합니다. */
{CONTENT_CSS.replace("body {", "#fallback {", 1)}
</style>
</head>
<body>
<div id="wrap">
  <div id="editor">{inner_html}</div>
  <div id="note">이미지 칸은 통째로 옮기거나 지울 수 있습니다. 안의 그림만 따로 바꾸지는 마세요.</div>
</div>

<script>
window.__dirty = false;
window.__ready = false;
window.__ck = null;

function markDirty() {{ window.__dirty = true; }}

/* 파이썬에서 부르는 두 함수 */
function setContent(html) {{
  if (window.__ck) window.__ck.setData(html);
  else document.getElementById('fallback').innerHTML = html;
  window.__dirty = false;
}}
function getContent() {{
  return window.__ck ? window.__ck.getData()
                     : document.getElementById('fallback').innerHTML;
}}

/* 커서 자리에 이미지 덩어리를 넣습니다. 파이썬이 파일을 images/ 로 복사한 뒤
   이 함수를 부릅니다. html 은 dsl_html._img_html() 이 만든 것과 같은 모양입니다. */
function insertImageBlock(html) {{
  if (window.__ck) {{
    window.__ck.insertHtml(html, 'unfiltered_html');
  }} else {{
    var d = document.getElementById('fallback');
    if (d) d.insertAdjacentHTML('beforeend', html);
  }}
  markDirty();
}}

/* CDN 을 못 받으면 contenteditable 로 전환 (오프라인 대비) */
function useFallback() {{
  var src = document.getElementById('editor');
  if (!src) return;
  var div = document.createElement('div');
  div.id = 'fallback';
  div.contentEditable = 'true';
  div.innerHTML = src.innerHTML;
  src.replaceWith(div);
  div.addEventListener('input', markDirty);
  window.__ready = true;
}}

var s = document.createElement('script');
s.src = "{CKEDITOR_URL}";
s.onload = function () {{
  try {{
    CKEDITOR.replace('editor', {{
      /* 자체 문법에서 온 태그·class·data 속성을 하나도 건드리지 않고 보존 */
      allowedContent: true,
      extraPlugins: 'colorbutton',
      removePlugins: 'elementspath',
      resize_enabled: false,
      height: 430,
      language: 'ko',
      /* 로컬 파일만 편집하는 사내용 도구라 버전 점검 배너는 끕니다
         (외부 입력을 받지 않아 이 배너가 경고하는 위험이 해당되지 않습니다) */
      versionCheck: false,
      toolbar: [
        {{ name: 'undo',   items: ['Undo', 'Redo'] }},
        {{ name: 'styles', items: ['Format'] }},
        {{ name: 'basic',  items: ['Bold', 'Italic', 'Underline', 'Strike'] }},
        {{ name: 'color',  items: ['TextColor', 'BGColor', 'RemoveFormat'] }},
        {{ name: 'para',   items: ['JustifyLeft', 'JustifyCenter', 'JustifyRight'] }},
        {{ name: 'insert', items: ['Link', 'Unlink', 'Table'] }},
        {{ name: 'blocks', items: ['Blockquote', 'HorizontalRule'] }}
      ],
      format_tags: 'p;h3',
      colorButton_enableMore: false,
      colorButton_colors: '{config.COLOR_KEY.lstrip("#")}/강조 파랑,'
                        + '{config.COLOR_WARN.lstrip("#")}/주의 빨강,'
                        + '{config.COLOR_MARK.lstrip("#")}/형광펜 노랑,'
                        + '1b1f27/기본 검정'
    }});
    CKEDITOR.instances.editor.on('instanceReady', function (ev) {{
      window.__ck = CKEDITOR.instances.editor;
      window.__ck.on('change', markDirty);

      /* 편집 영역은 iframe 이라 바깥 페이지의 <style> 이 닿지 않습니다.
         이미지 크기 제한·줄간격 같은 본문 CSS 를 iframe 문서에 직접 넣어줍니다. */
      try {{
        var doc = ev.editor.document.$;
        var st = doc.createElement('style');
        st.appendChild(doc.createTextNode({_CONTENT_CSS_JS}));
        (doc.head || doc.getElementsByTagName('head')[0]).appendChild(st);
      }} catch (e) {{ /* 스타일 주입 실패해도 편집 자체는 됩니다 */ }}

      window.__ready = true;
    }});
    /* 10초 안에 준비 안 되면 대체 편집기로 */
    setTimeout(function () {{ if (!window.__ready) useFallback(); }}, 10000);
  }} catch (e) {{
    window.__ckError = e && e.message ? e.message : String(e);
    useFallback();
  }}
}};
s.onerror = function () {{ useFallback(); }};
document.head.appendChild(s);
</script>
</body>
</html>"""
