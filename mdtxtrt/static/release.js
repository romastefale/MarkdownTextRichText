(() => {
'use strict'

const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null
const editor = document.getElementById('editor')
const toolbar = document.getElementById('toolbar')
const draftName = document.getElementById('draftName')
const saveState = document.getElementById('saveState')
const editTab = document.getElementById('editTab')
const previewTab = document.getElementById('previewTab')
const editorPane = document.getElementById('editorPane')
const previewPane = document.getElementById('previewPane')
const mechanismBadge = document.getElementById('mechanismBadge')
const telegramPreview = document.getElementById('telegramPreview')
const previewWarnings = document.getElementById('previewWarnings')
const projectionText = document.getElementById('projectionText')
const banner = document.getElementById('sessionBanner')
const modal = document.getElementById('modal')
const modalTitle = document.getElementById('modalTitle')
const modalBody = document.getElementById('modalBody')
const fileInput = document.getElementById('importFile')
const mediaInput = document.getElementById('mediaFile')
const toast = document.getElementById('toast')
const toastText = document.getElementById('toastText')
const mainButton = tg ? (tg.MainButton || tg.BottomButton || null) : null
const LOCAL_KEY = 'mdtxtrt.release.local.v1'
const CHECKPOINT_MS = 5 * 60 * 1000

let state = {
  draft: null,
  document: null,
  session: {scroll_y: 0, active_node_id: null, selection: null},
  destinations: [],
  dirty: false,
  busy: false,
  deleted: null,
  view: 'edit',
  preview: null,
}
let editTimer = null
let checkpointTimer = null

function uid(prefix) {
  const values = crypto.getRandomValues(new Uint32Array(4))
  return prefix + '_' + Array.from(values).join('')
}

function emptyDocument() {
  const now = Date.now()
  return {schema: 'mdtxtrt.document/v1', id: uid('doc'), created_at_ms: now, updated_at_ms: now, nodes: [], metadata: {}}
}

function initData() { return tg ? String(tg.initData || '').trim() : '' }
function htmlEscape(value) { const d = document.createElement('div'); d.textContent = String(value ?? ''); return d.innerHTML }
function stripHtml(value) { const d = document.createElement('div'); d.innerHTML = String(value || ''); return d.textContent || '' }
function makeNode(type, values = {}) { return Object.assign({id: uid('node'), type}, values) }
function nodes() { state.document || (state.document = emptyDocument()); state.document.nodes || (state.document.nodes = []); return state.document.nodes }
function nodeById(id) { return nodes().find(node => node.id === id) }
function indexById(id) { return nodes().findIndex(node => node.id === id) }
function isEmpty() { return !nodes().some(node => nodeText(node).trim()) }

function authHeaders() {
  const raw = initData()
  const headers = {'Content-Type': 'application/json'}
  if (raw) {
    headers['X-Telegram-Init-Data'] = raw
    headers.Authorization = 'tma ' + raw
  }
  return headers
}

async function api(path, payload = {}) {
  const raw = initData()
  const response = await fetch(path, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(Object.assign({init_data: raw}, payload)),
  })
  const data = await response.json().catch(() => ({ok: false, error: 'Resposta inválida do servidor.'}))
  if (!response.ok || data.ok === false) {
    const error = new Error(data.error || `HTTP ${response.status}`)
    error.status = response.status
    error.data = data
    throw error
  }
  return data
}

function showBanner(text, kind = '') {
  banner.textContent = text
  banner.className = 'banner' + (kind ? ' ' + kind : '')
}
function hideBanner() { banner.className = 'banner hidden'; banner.textContent = '' }

function setSaveState(text, error = false) {
  saveState.textContent = text
  saveState.classList.toggle('error', error)
}

function openModal(title, content) {
  modalTitle.textContent = title
  modalBody.innerHTML = ''
  if (typeof content === 'string') modalBody.innerHTML = content
  else if (content) modalBody.appendChild(content)
  modal.classList.remove('hidden')
  syncBackButton()
}
function closeModal() { modal.classList.add('hidden'); modalBody.innerHTML = ''; syncBackButton() }
document.getElementById('modalClose').onclick = closeModal
modal.addEventListener('click', event => { if (event.target === modal) closeModal() })

function toastUndo(message, callback) {
  toastText.textContent = message
  toast.classList.remove('hidden')
  const button = document.getElementById('toastUndo')
  button.onclick = () => { toast.classList.add('hidden'); if (callback) callback() }
  clearTimeout(toast._timer)
  toast._timer = setTimeout(() => toast.classList.add('hidden'), 6000)
}

function mirrorLocal() {
  try {
    localStorage.setItem(LOCAL_KEY, JSON.stringify({
      saved_at_ms: Date.now(),
      draft_id: state.draft && state.draft.id,
      revision_id: state.draft && state.draft.revision_id,
      document: state.document,
      session: captureSession(),
    }))
  } catch (_) {}
}
function localMirror() { try { return JSON.parse(localStorage.getItem(LOCAL_KEY) || 'null') } catch (_) { return null } }

function captureSession() {
  const selected = selectedBlock()
  return {
    scroll_y: editorPane.scrollTop,
    active_node_id: selected ? selected.dataset.id : null,
    selection: state.session.selection || null,
  }
}

function setDraft(draft) {
  state.draft = draft || null
  state.document = draft && draft.document ? structuredClone(draft.document) : emptyDocument()
  state.session = draft && draft.session ? structuredClone(draft.session) : {scroll_y: 0, active_node_id: null, selection: null}
  state.dirty = false
  state.preview = null
  draftName.textContent = draft && draft.name ? draft.name : 'Novo documento'
  setSaveState(draft ? 'salvo' : 'local')
  render()
  mirrorLocal()
  updateNativeSend()
}

function markDirty(eventType = 'edit') {
  state.document || (state.document = emptyDocument())
  state.document.updated_at_ms = Date.now()
  state.dirty = true
  state.preview = null
  state.lastEventType = eventType
  setSaveState('salvando…')
  mirrorLocal()
  updateNativeSend()
  clearTimeout(editTimer)
  editTimer = setTimeout(() => checkpoint('edit'), 1300)
}

async function checkpoint(eventType = 'checkpoint', force = false) {
  if (state.busy || (!state.dirty && !force)) return
  if (!state.draft) {
    if (!state.dirty && !force) return
    await createCurrentDraft()
    return
  }
  state.busy = true
  try {
    const result = await api('/api/draft/revise', {
      draft_id: state.draft.id,
      expected_revision_id: state.draft.revision_id,
      document: structuredClone(state.document),
      session: captureSession(),
      event_type: eventType,
      group_key: eventType === 'edit' ? 'typing' : eventType,
    })
    state.draft = result.draft
    state.document = structuredClone(result.draft.document)
    state.dirty = false
    draftName.textContent = result.draft.name
    setSaveState('salvo')
    mirrorLocal()
  } catch (error) {
    if (error.status === 409 && error.data && error.data.server) showConflict(error.data.server)
    else if (error.status === 401) {
      setSaveState('sessão expirada', true)
      showBanner('A sessão Telegram expirou. O espelho local foi preservado; reabra a Mini App pelo Telegram.', 'error')
    } else {
      setSaveState('falha ao salvar', true)
      showBanner(error.message || 'Falha ao salvar; o espelho local foi mantido.', 'error')
    }
  } finally {
    state.busy = false
  }
}

function showConflict(serverDraft) {
  const local = localMirror()
  const wrap = document.createElement('div')
  wrap.className = 'choice-list'
  const p = document.createElement('p')
  p.textContent = 'Servidor e espelho local divergem. Escolha explicitamente qual versão continuar; nenhuma mesclagem automática será feita.'
  wrap.appendChild(p)
  addChoice(wrap, 'Usar versão do servidor', () => { setDraft(serverDraft); closeModal() })
  addChoice(wrap, 'Usar versão local', async () => {
    if (!local || !state.draft) return
    const result = await api('/api/draft/recover-local', {
      confirmed_choice: 'local',
      draft_id: state.draft.id,
      source_revision_id: serverDraft.revision_id,
      document: local.document,
      session: local.session,
    })
    setDraft(result.draft)
    closeModal()
  })
  openModal('Conflito de revisão', wrap)
}

function selectedBlock() { return editor.querySelector('.block.selected') }
function selectBlock(element) {
  editor.querySelectorAll('.block.selected').forEach(item => item.classList.remove('selected'))
  if (element) {
    element.classList.add('selected')
    state.session.active_node_id = element.dataset.id
  }
  updateToolbarState()
}

function insertNode(node, afterId = null) {
  const list = nodes()
  if (afterId) {
    const index = indexById(afterId)
    list.splice(index < 0 ? list.length : index + 1, 0, node)
  } else list.push(node)
  markDirty('insert')
  render(node.id)
}

function deleteNode(id) {
  const index = indexById(id)
  if (index < 0) return
  const removed = nodes().splice(index, 1)[0]
  state.deleted = {node: structuredClone(removed), index}
  markDirty('delete')
  render()
  toastUndo('Elemento excluído.', () => {
    if (!state.deleted) return
    nodes().splice(state.deleted.index, 0, state.deleted.node)
    const restored = state.deleted.node.id
    state.deleted = null
    markDirty('undo_delete')
    render(restored)
  })
}

function duplicateNode(id) {
  const index = indexById(id)
  if (index < 0) return
  const clone = structuredClone(nodes()[index])
  clone.id = uid('node')
  nodes().splice(index + 1, 0, clone)
  markDirty('duplicate')
  render(clone.id)
}

function blockTools(node) {
  const tools = document.createElement('div')
  tools.className = 'block-tools'
  const duplicate = document.createElement('button'); duplicate.type = 'button'; duplicate.textContent = '◧'; duplicate.title = 'Duplicar'
  duplicate.onclick = event => { event.stopPropagation(); duplicateNode(node.id) }
  const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = '×'; remove.title = 'Excluir'
  remove.onclick = event => { event.stopPropagation(); deleteNode(node.id) }
  tools.append(duplicate, remove)
  return tools
}

function editable(node, placeholder = 'Digite…') {
  const div = document.createElement('div')
  div.className = 'rich-text'
  div.contentEditable = 'true'
  div.dataset.placeholder = placeholder
  div.innerHTML = node.html || ''
  div.addEventListener('input', () => { node.html = div.innerHTML; markDirty('edit') })
  div.addEventListener('focus', () => { selectBlock(div.closest('.block')); ensureCaretVisible(div) })
  div.addEventListener('keyup', rememberSelection)
  div.addEventListener('mouseup', rememberSelection)
  return div
}

function renderNode(node) {
  const block = document.createElement('article')
  block.className = `block ${node.type}`
  block.dataset.id = node.id
  block.appendChild(blockTools(node))
  block.onclick = event => { if (!event.target.closest('button')) selectBlock(block) }
  const typ = node.type
  if (typ === 'paragraph') block.appendChild(editable(node))
  else if (typ === 'heading') {
    const level = Math.max(1, Math.min(3, Number(node.level || 2)))
    block.classList.add(`heading-${level}`)
    block.appendChild(editable(node, `Título H${level}…`))
  } else if (typ === 'blockquote' || typ === 'pullquote') {
    block.classList.add('blockquote')
    block.appendChild(editable(node, 'Citação…'))
  } else if (typ === 'footer') {
    block.classList.add('footer-block')
    block.appendChild(editable(node, 'Rodapé…'))
  } else if (typ === 'details') renderDetails(block, node)
  else if (typ === 'code') renderTextArea(block, node, 'text', 'Código', 'code-block')
  else if (typ === 'math') renderTextArea(block, node, 'expression', 'Expressão LaTeX', 'math-block')
  else if (typ === 'divider') block.appendChild(document.createElement('hr'))
  else if (typ === 'list') renderList(block, node)
  else if (typ === 'table') renderTable(block, node)
  else if (typ === 'media') renderMedia(block, node)
  else if (typ === 'map') renderMap(block, node)
  else if (typ === 'buttons') renderButtons(block, node)
  else if (typ === 'anchor') renderAnchor(block, node)
  else if (typ === 'raw_markdown') renderRaw(block, node)
  else block.appendChild(editable(node))
  return block
}

function renderTextArea(block, node, key, placeholder, className) {
  block.classList.add(className)
  const area = document.createElement('textarea')
  area.value = node[key] || ''
  area.placeholder = placeholder
  area.oninput = () => { node[key] = area.value; markDirty('edit') }
  area.onfocus = () => selectBlock(block)
  block.appendChild(area)
}

function renderDetails(block, node) {
  block.classList.add('details-card')
  const details = document.createElement('details')
  details.open = node.open !== false
  const summary = document.createElement('summary')
  summary.contentEditable = 'true'
  summary.innerHTML = node.summary_html || 'Detalhes'
  summary.oninput = () => { node.summary_html = summary.innerHTML; markDirty('edit') }
  details.appendChild(summary)
  const bodyNode = {html: node.html || ''}
  const body = editable(bodyNode, 'Conteúdo…')
  body.oninput = () => { node.html = body.innerHTML; markDirty('edit') }
  details.appendChild(body)
  details.ontoggle = () => { node.open = details.open; markDirty('edit') }
  block.appendChild(details)
}

function renderList(block, node) {
  const list = document.createElement(node.ordered ? 'ol' : 'ul')
  list.className = 'list-editor'
  ;(node.items || []).forEach((item, index) => {
    const li = document.createElement('li')
    if (item && typeof item === 'object' && item.checked !== undefined && item.checked !== null) {
      const checkbox = document.createElement('input')
      checkbox.type = 'checkbox'; checkbox.checked = !!item.checked
      checkbox.onchange = () => { item.checked = checkbox.checked; markDirty('edit') }
      li.appendChild(checkbox)
    }
    const span = document.createElement('span')
    span.contentEditable = 'true'
    span.innerHTML = typeof item === 'object' ? (item.html || '') : String(item || '')
    span.oninput = () => {
      if (typeof node.items[index] !== 'object') node.items[index] = {html: span.innerHTML}
      else node.items[index].html = span.innerHTML
      markDirty('edit')
    }
    li.appendChild(span)
    list.appendChild(li)
  })
  const add = document.createElement('button'); add.type = 'button'; add.textContent = '+ item'
  add.onclick = () => { (node.items || (node.items = [])).push({html: ''}); markDirty('edit'); render(node.id) }
  block.append(list, add)
}

function renderTable(block, node) {
  const wrap = document.createElement('div'); wrap.className = 'table-wrap'
  const table = document.createElement('table'); table.className = 'rich-table'
  const rows = node.rows || (node.rows = [['', ''], ['', '']])
  rows.forEach((row, r) => {
    const tr = document.createElement('tr')
    row.forEach((cell, c) => {
      const value = typeof cell === 'object' ? cell : {text: cell}
      const td = document.createElement(value.header || r === 0 ? 'th' : 'td')
      td.contentEditable = 'true'
      td.textContent = value.text || stripHtml(value.html || '')
      td.oninput = () => { rows[r][c] = Object.assign({}, value, {text: td.textContent || ''}); markDirty('edit') }
      tr.appendChild(td)
    })
    table.appendChild(tr)
  })
  wrap.appendChild(table)
  const actions = document.createElement('div'); actions.className = 'row'
  addAction(actions, '+ linha', () => { rows.push(Array(rows[0]?.length || 2).fill('')); markDirty('edit'); render(node.id) })
  addAction(actions, '+ coluna', () => { rows.forEach(row => row.push('')); markDirty('edit'); render(node.id) })
  block.append(wrap, actions)
}

function renderMedia(block, node) {
  block.classList.add('media-card')
  const title = document.createElement('strong'); title.textContent = node.name || 'Mídia'
  const info = document.createElement('div'); info.className = 'muted'; info.textContent = node.mime || node.kind || 'arquivo'
  const choose = document.createElement('button'); choose.type = 'button'; choose.textContent = node.blob_id ? 'Substituir arquivo' : 'Escolher arquivo'
  choose.onclick = () => { mediaInput.dataset.node = node.id; mediaInput.click() }
  block.append(title, info, choose)
}

function renderMap(block, node) {
  block.classList.add('map-card')
  const name = document.createElement('input'); name.value = node.name || ''; name.placeholder = 'Nome'; name.oninput = () => { node.name = name.value; markDirty('edit') }
  const coords = document.createElement('div'); coords.className = 'muted'; coords.textContent = node.latitude != null && node.longitude != null ? `${node.latitude}, ${node.longitude}` : 'Localização ainda não recebida'
  const choose = document.createElement('button'); choose.type = 'button'; choose.textContent = 'Escolher localização no Telegram'; choose.onclick = () => requestMap(node)
  block.append(name, coords, choose)
}

function renderButtons(block, node) {
  block.classList.add('buttons-card')
  const row = document.createElement('div'); row.className = 'row'
  ;(node.items || []).forEach((item, index) => {
    const button = document.createElement('button'); button.type = 'button'; button.className = 'primary'; button.textContent = stripHtml(item.html || item.text || 'Botão')
    button.onclick = () => editRichButton(node, index)
    row.appendChild(button)
  })
  const add = document.createElement('button'); add.type = 'button'; add.textContent = '+ botão'; add.onclick = () => editRichButton(node, -1)
  block.append(row, add)
}

function renderAnchor(block, node) {
  const form = document.createElement('div'); form.className = 'row'
  const input = document.createElement('input'); input.value = node.name || ''; input.placeholder = 'Nome da âncora'; input.oninput = () => { node.name = input.value; markDirty('edit') }
  form.appendChild(input); block.appendChild(form)
}

function renderRaw(block, node) {
  block.classList.add('raw-panel')
  const badge = document.createElement('small'); badge.className = 'muted'; badge.textContent = 'Markdown cru preservado'
  const area = document.createElement('textarea'); area.value = node.raw || ''; area.oninput = () => { node.raw = area.value; markDirty('edit') }
  block.append(badge, area)
}

function render(selectId = null) {
  editor.innerHTML = ''
  nodes().forEach(node => editor.appendChild(renderNode(node)))
  if (!nodes().length) {
    const p = document.createElement('p'); p.className = 'muted'; p.textContent = 'Documento vazio.'; editor.appendChild(p)
  }
  const target = selectId || state.session.active_node_id
  if (target) {
    const element = editor.querySelector(`[data-id="${CSS.escape(target)}"]`)
    if (element) selectBlock(element)
  }
  updateNativeSend()
}

function createBlock(type, extra = {}) {
  const selected = selectedBlock()
  const after = selected && selected.dataset.id
  let node
  if (type === 'heading') node = makeNode('heading', {level: extra.level || 2, html: ''})
  else if (type === 'blockquote') node = makeNode('blockquote', {html: '', expandable: !!extra.expandable})
  else if (type === 'details') node = makeNode('details', {summary_html: 'Detalhes', html: '', open: true})
  else if (type === 'code') node = makeNode('code', {language: '', text: ''})
  else if (type === 'math') node = makeNode('math', {expression: '', display: true})
  else if (type === 'list') node = makeNode('list', {ordered: !!extra.ordered, items: [{html: '', checked: extra.tasks ? false : undefined}]})
  else if (type === 'table') node = makeNode('table', {rows: [[{text: '', header: true}, {text: '', header: true}], ['', '']], bordered: true})
  else if (type === 'media') node = makeNode('media', {name: 'Mídia', kind: extra.kind || 'document', mime: '', blob_id: null})
  else if (type === 'map') node = makeNode('map', {name: '', latitude: null, longitude: null, address: null})
  else if (type === 'buttons') node = makeNode('buttons', {items: []})
  else if (type === 'divider') node = makeNode('divider')
  else if (type === 'footer') node = makeNode('footer', {html: ''})
  else if (type === 'anchor') node = makeNode('anchor', {name: ''})
  else node = makeNode('paragraph', {html: ''})
  insertNode(node, after)
}

document.getElementById('addParagraph').onclick = () => createBlock('paragraph')

function rememberSelection() {
  const selection = window.getSelection()
  const block = selectedBlock()
  if (!selection || !block || !selection.rangeCount) return
  const editableNode = block.querySelector('[contenteditable=true]')
  if (!editableNode || !editableNode.contains(selection.anchorNode)) return
  state.session.selection = {node_id: block.dataset.id}
}

function execInline(tag) {
  const command = {strong: 'bold', em: 'italic', u: 'underline', s: 'strikeThrough', code: null, mark: null, 'tg-spoiler': null}[tag]
  const block = selectedBlock()
  if (!block) return
  const editableNode = block.querySelector('[contenteditable=true]')
  if (!editableNode) return
  editableNode.focus()
  if (command) document.execCommand(command, false)
  else {
    const selection = window.getSelection()
    if (!selection || !selection.rangeCount || selection.isCollapsed) return
    const range = selection.getRangeAt(0)
    const wrapper = document.createElement(tag === 'tg-spoiler' ? 'span' : tag)
    if (tag === 'tg-spoiler') wrapper.dataset.spoiler = 'true'
    try { range.surroundContents(wrapper) } catch (_) { return }
  }
  editableNode.dispatchEvent(new InputEvent('input', {bubbles: true}))
  updateToolbarState()
}

function updateToolbarState() {
  toolbar.querySelectorAll('[data-inline]').forEach(button => button.classList.remove('active'))
  const block = selectedBlock()
  if (!block) return
  const editableNode = block.querySelector('[contenteditable=true]')
  if (!editableNode) return
  const selection = window.getSelection()
  if (!selection || !selection.anchorNode || !editableNode.contains(selection.anchorNode)) return
  let element = selection.anchorNode.nodeType === 1 ? selection.anchorNode : selection.anchorNode.parentElement
  while (element && element !== editableNode) {
    const tag = element.tagName && element.tagName.toLowerCase()
    const key = tag === 'b' ? 'strong' : tag === 'i' ? 'em' : tag
    if (key) toolbar.querySelector(`[data-inline="${key}"]`)?.classList.add('active')
    if (element.dataset && element.dataset.spoiler) toolbar.querySelector('[data-inline="tg-spoiler"]')?.classList.add('active')
    element = element.parentElement
  }
}

toolbar.addEventListener('click', event => {
  const button = event.target.closest('button')
  if (!button) return
  if (button.dataset.heading) return createBlock('heading', {level: Number(button.dataset.heading)})
  if (button.dataset.inline) return execInline(button.dataset.inline)
  if (button.dataset.block) return createBlock(button.dataset.block)
  if (button.dataset.action === 'link') return createLink()
})

function createLink() {
  const block = selectedBlock(); const editableNode = block && block.querySelector('[contenteditable=true]')
  if (!editableNode) return
  const url = prompt('URL')
  if (!url) return
  editableNode.focus(); document.execCommand('createLink', false, url)
  editableNode.dispatchEvent(new InputEvent('input', {bubbles: true}))
}

function showMoreMenu() {
  const wrap = document.createElement('div'); wrap.className = 'choice-list'
  const groups = [
    ['Formatação adicional', [
      ['Tachado', () => execInline('s')], ['Spoiler', () => execInline('tg-spoiler')], ['Marcado', () => execInline('mark')], ['Limpar formatação', clearFormatting],
    ]],
    ['Estrutura', [
      ['Divisor', () => createBlock('divider')], ['Rodapé', () => createBlock('footer')], ['Bloco recolhível', () => createBlock('details')], ['Citação expansível', () => createBlock('blockquote', {expandable: true})],
    ]],
    ['Listas', [
      ['Marcadores', () => createBlock('list')], ['Numerada', () => createBlock('list', {ordered: true})], ['Tarefas', () => createBlock('list', {tasks: true})],
    ]],
    ['Dados estruturados', [
      ['Tabela', () => createBlock('table')], ['Fórmula', () => createBlock('math')], ['Âncora', () => createBlock('anchor')],
    ]],
    ['Mídia e interação', [
      ['Imagem/arquivo', () => createBlock('media')], ['Mapa', () => createBlock('map')], ['Botões Rich', () => createBlock('buttons')],
    ]],
    ['Documento', [
      ['Importar .md/.txt', () => { closeModal(); fileInput.click() }], ['Localizar e substituir', () => { closeModal(); findReplace() }], ['Rascunhos', () => { closeModal(); showDrafts() }],
    ]],
  ]
  groups.forEach(([title, actions]) => {
    const details = document.createElement('details'); const summary = document.createElement('summary'); summary.textContent = title; details.appendChild(summary)
    const list = document.createElement('div'); list.className = 'choice-list'
    actions.forEach(([label, run]) => addChoice(list, label, () => { closeModal(); run() }))
    details.appendChild(list); wrap.appendChild(details)
  })
  openModal('Adicionar', wrap)
}
document.getElementById('moreButton').onclick = showMoreMenu

function clearFormatting() {
  const block = selectedBlock(); const editableNode = block && block.querySelector('[contenteditable=true]')
  if (!editableNode) return
  editableNode.focus(); document.execCommand('removeFormat', false)
  editableNode.querySelectorAll('a').forEach(a => a.replaceWith(document.createTextNode(a.textContent || '')))
  editableNode.dispatchEvent(new InputEvent('input', {bubbles: true}))
}

function addChoice(parent, label, run, detail = '') {
  const button = document.createElement('button'); button.type = 'button'; button.className = 'choice'
  const span = document.createElement('span'); span.textContent = label; button.appendChild(span)
  if (detail) { const small = document.createElement('small'); small.className = 'muted'; small.textContent = detail; button.appendChild(small) }
  button.onclick = run; parent.appendChild(button); return button
}
function addAction(parent, label, run, primary = false) {
  const button = document.createElement('button'); button.type = 'button'; button.textContent = label; if (primary) button.className = 'primary'; button.onclick = run; parent.appendChild(button); return button
}

function editRichButton(node, index) {
  const current = index >= 0 ? (node.items || [])[index] || {} : {}
  const form = document.createElement('form'); form.className = 'form'
  form.innerHTML = `<label>Texto<input name="text" value="${htmlEscape(stripHtml(current.html || current.text || ''))}"></label><label>URL<input name="url" value="${htmlEscape(current.url || 'https://')}"></label><label>Estilo<select name="style"><option value="primary">primary</option><option value="success">success</option><option value="danger">danger</option><option value="link">link</option></select></label><div class="row"><button type="button" data-cancel>Cancelar</button><button class="primary" type="submit">Aplicar</button></div>`
  form.elements.style.value = current.style || 'primary'
  form.querySelector('[data-cancel]').onclick = closeModal
  form.onsubmit = event => {
    event.preventDefault(); const data = new FormData(form)
    const item = {type: 'url', html: htmlEscape(data.get('text') || ''), url: String(data.get('url') || ''), style: String(data.get('style') || 'primary')}
    node.items || (node.items = [])
    if (index < 0) node.items.push(item); else node.items[index] = item
    markDirty('edit_button'); closeModal(); render(node.id)
  }
  openModal(index < 0 ? 'Novo botão Rich' : 'Editar botão Rich', form)
}

function findReplace() {
  const form = document.createElement('form'); form.className = 'form'
  form.innerHTML = '<label>Localizar<input name="find"></label><label>Substituir por<input name="replace"></label><div class="row"><button type="button" data-cancel>Cancelar</button><button class="primary" type="submit">Substituir</button></div>'
  form.querySelector('[data-cancel]').onclick = closeModal
  form.onsubmit = event => {
    event.preventDefault(); const data = new FormData(form); const find = String(data.get('find') || ''); const replacement = String(data.get('replace') || '')
    if (!find) return
    let count = 0
    nodes().forEach(node => {
      for (const key of ['html', 'summary_html', 'text', 'expression', 'raw']) {
        if (typeof node[key] === 'string' && node[key].includes(find)) { count += node[key].split(find).length - 1; node[key] = node[key].split(find).join(replacement) }
      }
      if (node.type === 'list') (node.items || []).forEach(item => { if (item && typeof item.html === 'string' && item.html.includes(find)) { count += item.html.split(find).length - 1; item.html = item.html.split(find).join(replacement) } })
    })
    if (count) { markDirty('replace'); render() }
    closeModal(); showBanner(count ? `${count} ocorrência(s) substituída(s).` : 'Nenhuma ocorrência encontrada.')
  }
  openModal('Localizar e substituir', form)
}

async function createCurrentDraft() {
  const result = await api('/api/draft/create', {document: structuredClone(state.document || emptyDocument()), session: captureSession()})
  state.draft = result.draft; state.document = structuredClone(result.draft.document); state.dirty = false; draftName.textContent = result.draft.name; setSaveState('salvo'); mirrorLocal(); return state.draft
}
async function newDraft() { await checkpoint('switch', true); setDraft(null); closeModal() }
async function loadDraft(id) { await checkpoint('switch', true); const result = await api('/api/draft/load', {draft_id: id}); setDraft(result.draft); closeModal(); requestAnimationFrame(() => { editorPane.scrollTop = result.draft.session?.scroll_y || 0 }) }
async function showDrafts() {
  try {
    const data = await api('/api/bootstrap', {})
    state.destinations = data.destinations || []
    const wrap = document.createElement('div'); wrap.className = 'choice-list'
    ;(data.drafts || []).forEach(item => addChoice(wrap, item.name || 'Sem título', () => loadDraft(item.id), new Date(item.updated_at_ms).toLocaleString('pt-BR')))
    addChoice(wrap, 'Novo documento', newDraft)
    openModal('Rascunhos', wrap)
  } catch (error) { showBanner(error.message, 'error') }
}

async function doUndo() { if (!state.draft) return; if (state.dirty) await checkpoint('before_undo', true); try { const result = await api('/api/draft/undo', {draft_id: state.draft.id}); setDraft(result.draft) } catch (e) { showBanner(e.message, 'error') } }
async function doRedo() { if (!state.draft) return; try { const result = await api('/api/draft/redo', {draft_id: state.draft.id}); if (result.draft.redo_requires_choice) showRedoChoices(result.draft); else setDraft(result.draft) } catch (e) { showBanner(e.message, 'error') } }
function showRedoChoices(draft) { const wrap = document.createElement('div'); wrap.className = 'choice-list'; (draft.redo_choices || []).forEach(choice => addChoice(wrap, new Date(choice.created_at_ms).toLocaleString('pt-BR') + ' · ' + choice.event_type, async () => { const result = await api('/api/draft/redo', {draft_id: state.draft.id, revision_id: choice.id}); setDraft(result.draft); closeModal() })); openModal('Escolher ramificação', wrap) }

async function importText(text, mode = null) {
  try {
    const result = await api('/api/import/text', {text, mode})
    if (result.requires_mode_choice) {
      const wrap = document.createElement('div'); wrap.className = 'choice-list'
      addChoice(wrap, 'Interpretar Markdown', () => { closeModal(); importText(text, 'markdown') })
      addChoice(wrap, 'Manter literal', () => { closeModal(); importText(text, 'literal') })
      return openModal('Texto parece Markdown', wrap)
    }
    if (result.draft) setDraft(result.draft)
  } catch (error) { showBanner(error.message, 'error') }
}

fileInput.onchange = async () => {
  const file = fileInput.files && fileInput.files[0]; if (!file) return
  const form = new FormData(); form.append('file', file); form.append('init_data', initData())
  try {
    const response = await fetch('/api/import/file', {method: 'POST', body: form, headers: initData() ? {'X-Telegram-Init-Data': initData()} : undefined})
    const data = await response.json()
    if (response.status === 409 && data.requires_encoding_choice) return chooseEncoding(data.import_key, data.choices)
    if (!response.ok || data.ok === false) throw new Error(data.error || 'Falha ao importar')
    if (data.draft) setDraft(data.draft)
  } catch (error) { showBanner(error.message, 'error') } finally { fileInput.value = '' }
}
function chooseEncoding(key, choices) { const wrap = document.createElement('div'); wrap.className = 'choice-list'; choices.forEach(encoding => addChoice(wrap, encoding, async () => { try { const result = await api('/api/import/resolve', {import_key: key, encoding}); if (result.draft) setDraft(result.draft); closeModal() } catch (error) { showBanner(error.message, 'error') } })); openModal('Escolher encoding', wrap) }

mediaInput.onchange = async () => {
  const file = mediaInput.files && mediaInput.files[0]; const node = nodeById(mediaInput.dataset.node); if (!file || !node) return
  if (!state.draft) await createCurrentDraft()
  const form = new FormData(); form.append('file', file); form.append('draft_id', state.draft.id); form.append('relation', 'media'); form.append('init_data', initData())
  try {
    const response = await fetch('/api/blob/upload', {method: 'POST', body: form, headers: initData() ? {'X-Telegram-Init-Data': initData()} : undefined})
    const data = await response.json(); if (!response.ok || data.ok === false) throw new Error(data.error || 'Falha no upload')
    node.blob_id = data.blob.id; node.name = data.blob.name; node.mime = data.blob.mime; node.kind = mediaKind(data.blob.mime); markDirty('media'); render(node.id)
  } catch (error) { showBanner(error.message, 'error') } finally { mediaInput.value = '' }
}
function mediaKind(mime) { if ((mime || '').startsWith('image/')) return 'photo'; if ((mime || '').startsWith('video/')) return 'video'; if ((mime || '').startsWith('audio/')) return 'audio'; return 'document' }

async function requestMap(node) {
  if (!state.draft) await createCurrentDraft()
  try {
    const result = await api('/api/map/request', {draft_id: state.draft.id, node_id: node.id})
    node.map_request_id = result.request.id; markDirty('map_request')
    if (result.telegram_url) { if (tg?.openTelegramLink) tg.openTelegramLink(result.telegram_url); else location.href = result.telegram_url }
    pollMap(node, result.request.id)
  } catch (error) { showBanner(error.message, 'error') }
}
async function pollMap(node, id) { for (let i = 0; i < 120; i++) { await new Promise(resolve => setTimeout(resolve, 1500)); try { const result = await api('/api/map/status', {request_id: id}); const req = result.request; if (req.status === 'received') { node.latitude = req.latitude; node.longitude = req.longitude; node.name = req.name || node.name; node.address = req.address || null; markDirty('map_received'); render(node.id); return } } catch (_) { return } } }

function nodeText(node) {
  if (['paragraph', 'heading', 'blockquote', 'pullquote', 'footer'].includes(node.type)) return stripHtml(node.html || '')
  if (node.type === 'code') return node.text || ''
  if (node.type === 'math') return node.expression || ''
  if (node.type === 'details') return stripHtml((node.summary_html || '') + ' ' + (node.html || ''))
  if (node.type === 'list') return (node.items || []).map(item => stripHtml(typeof item === 'object' ? item.html || '' : item)).join(' ')
  if (node.type === 'table') return (node.rows || []).flat().map(cell => typeof cell === 'object' ? (cell.text || stripHtml(cell.html || '')) : cell).join(' ')
  if (node.type === 'media') return node.name || node.blob_id || ''
  if (node.type === 'map') return node.name || (node.latitude != null ? `${node.latitude},${node.longitude}` : '')
  if (node.type === 'buttons') return (node.items || []).map(item => stripHtml(item.html || item.text || '')).join(' ')
  if (node.type === 'anchor') return node.name || ''
  if (node.type === 'raw_markdown') return node.raw || ''
  if (node.type === 'divider') return '—'
  return ''
}

function previewNode(node) {
  const typ = node.type
  if (typ === 'paragraph') return `<p>${node.html || ''}</p>`
  if (typ === 'heading') { const level = Math.max(1, Math.min(3, Number(node.level || 2))); return `<h${level}>${node.html || ''}</h${level}>` }
  if (typ === 'blockquote' || typ === 'pullquote') return `<blockquote>${node.html || ''}</blockquote>`
  if (typ === 'footer') return `<footer>${node.html || ''}</footer>`
  if (typ === 'details') return `<details${node.open !== false ? ' open' : ''}><summary>${node.summary_html || 'Detalhes'}</summary><p>${node.html || ''}</p></details>`
  if (typ === 'code') return `<pre><code>${htmlEscape(node.text || '')}</code></pre>`
  if (typ === 'math') return `<div><strong>ƒ</strong> ${htmlEscape(node.expression || '')}</div>`
  if (typ === 'divider') return '<hr>'
  if (typ === 'list') { const tag = node.ordered ? 'ol' : 'ul'; return `<${tag}>${(node.items || []).map(item => { const body = typeof item === 'object' ? item : {html: item}; const check = body.checked === undefined || body.checked === null ? '' : (body.checked ? '☑ ' : '☐ '); return `<li>${check}${body.html || ''}</li>` }).join('')}</${tag}>` }
  if (typ === 'table') return `<table>${(node.rows || []).map((row, r) => `<tr>${row.map(cell => { const value = typeof cell === 'object' ? cell : {text: cell}; const tag = value.header || r === 0 ? 'th' : 'td'; return `<${tag}>${htmlEscape(value.text || stripHtml(value.html || ''))}</${tag}>` }).join('')}</tr>`).join('')}</table>`
  if (typ === 'media') return `<div>▧ ${htmlEscape(node.name || 'Mídia')}</div>`
  if (typ === 'map') return `<div>⌖ ${htmlEscape(node.name || 'Mapa')} ${node.latitude != null ? htmlEscape(`${node.latitude}, ${node.longitude}`) : ''}</div>`
  if (typ === 'buttons') return `<div>${(node.items || []).map(item => `<span class="preview-button">${htmlEscape(stripHtml(item.html || item.text || 'Botão'))}</span>`).join('')}</div>`
  if (typ === 'anchor') return `<div class="muted">#${htmlEscape(node.name || '')}</div>`
  if (typ === 'raw_markdown') return `<pre>${htmlEscape(node.raw || '')}</pre>`
  return `<p>${htmlEscape(nodeText(node))}</p>`
}

async function refreshPreview() {
  if (!state.draft) await createCurrentDraft()
  if (state.dirty) await checkpoint('preflight', true)
  try {
    const data = await api('/api/conversion/review', {draft_id: state.draft.id, destination: 'telegram'})
    state.preview = data
    mechanismBadge.textContent = data.review.mechanism || data.review.recommended || 'Telegram'
    telegramPreview.innerHTML = nodes().map(previewNode).join('') || '<p class="muted">Documento vazio.</p>'
    projectionText.textContent = typeof data.review.projection === 'string' ? data.review.projection : JSON.stringify(data.review.projection, null, 2)
    const warnings = data.review.warnings || []
    if (warnings.length) {
      previewWarnings.innerHTML = warnings.map(item => `<div>${htmlEscape(item.message || String(item))}</div>`).join('')
      previewWarnings.classList.remove('hidden')
    } else { previewWarnings.innerHTML = ''; previewWarnings.classList.add('hidden') }
    return data
  } catch (error) { showBanner(error.message, 'error'); throw error }
}
document.getElementById('refreshPreview').onclick = refreshPreview

function setView(view) {
  state.view = view
  const preview = view === 'preview'
  editorPane.classList.toggle('hidden', preview)
  previewPane.classList.toggle('hidden', !preview)
  editTab.classList.toggle('active', !preview); editTab.setAttribute('aria-selected', String(!preview))
  previewTab.classList.toggle('active', preview); previewTab.setAttribute('aria-selected', String(preview))
  if (preview) refreshPreview()
  syncBackButton()
}
editTab.onclick = () => setView('edit')
previewTab.onclick = () => setView('preview')

async function sendTelegram() {
  if (isEmpty()) return
  setMainProgress(true)
  try {
    const preview = state.preview || await refreshPreview()
    if (!state.destinations.length) {
      const boot = await api('/api/bootstrap', {}); state.destinations = boot.destinations || []
    }
    if (!state.destinations.length) throw new Error('Nenhum destino Telegram autorizado. Envie um comando ao bot no chat de destino e reabra o editor.')
    openSendDialog(preview)
  } catch (error) { showBanner(error.message, 'error') } finally { setMainProgress(false) }
}

function openSendDialog(preview) {
  const form = document.createElement('form'); form.className = 'form'
  const destination = document.createElement('select'); destination.name = 'destination'
  state.destinations.forEach(item => { const option = document.createElement('option'); option.value = item.id; option.textContent = item.title || item.username || 'Destino autorizado'; destination.appendChild(option) })
  const renderer = document.createElement('select'); renderer.name = 'renderer'
  ;(preview.review.alternatives || []).filter(item => item.available !== false).forEach(item => { const option = document.createElement('option'); option.value = item.id; option.textContent = item.label || item.id; if (item.id === preview.review.recommended) option.selected = true; renderer.appendChild(option) })
  if (![...renderer.options].some(option => option.value === preview.review.recommended)) { const option = document.createElement('option'); option.value = preview.review.recommended; option.textContent = preview.review.mechanism || preview.review.recommended; option.selected = true; renderer.prepend(option) }
  const dLabel = document.createElement('label'); dLabel.textContent = 'Destino autorizado'; dLabel.appendChild(destination)
  const rLabel = document.createElement('label'); rLabel.textContent = 'Renderizador'; rLabel.appendChild(renderer)
  const note = document.createElement('small'); note.className = 'muted'; note.textContent = 'O navegador envia apenas destination_id. O servidor resolve o chat_id autorizado.'
  const row = document.createElement('div'); row.className = 'row'; addAction(row, 'Cancelar', closeModal); const send = addAction(row, 'Enviar', null, true); send.type = 'submit'
  form.append(dLabel, rLabel, note, row)
  form.onsubmit = async event => {
    event.preventDefault(); send.disabled = true; send.textContent = 'Enviando…'
    try {
      const result = await api('/api/telegram/send', {
        draft_id: state.draft.id,
        revision_id: preview.draft_revision_id,
        destination_id: destination.value,
        format: renderer.value,
        confirmed: true,
      })
      closeModal(); showPublicationSuccess(result)
    } catch (error) { showBanner(error.message, 'error'); send.disabled = false; send.textContent = 'Enviar' }
  }
  openModal('Enviar ao Telegram', form)
}

function showPublicationSuccess(result) {
  const wrap = document.createElement('div'); wrap.className = 'choice-list'
  const p = document.createElement('p'); p.textContent = result.message_id ? `Mensagem enviada. message_id: ${result.message_id}` : 'Mensagem enviada.'; wrap.appendChild(p)
  addChoice(wrap, 'Continuar editando', closeModal)
  addChoice(wrap, 'Novo documento', newDraft)
  openModal('Concluído', wrap)
}

async function exportDocument(destination) {
  if (!state.draft) await createCurrentDraft(); if (state.dirty) await checkpoint('export', true)
  try {
    const reviewed = await api('/api/conversion/review', {draft_id: state.draft.id, destination})
    const result = await api('/api/export', {draft_id: state.draft.id, revision_id: reviewed.draft_revision_id, destination})
    const mime = destination === 'txt' ? 'text/plain' : 'text/markdown'
    const blob = new Blob([result.content || ''], {type: mime}); const url = URL.createObjectURL(blob); const anchor = document.createElement('a'); anchor.href = url; anchor.download = result.filename || `MDTXTRT.${destination === 'txt' ? 'txt' : 'md'}`; anchor.click(); URL.revokeObjectURL(url)
  } catch (error) { showBanner(error.message, 'error') }
}

async function publishTelegraph() {
  if (!state.draft) await createCurrentDraft(); if (state.dirty) await checkpoint('telegraph', true)
  try {
    const reviewed = await api('/api/conversion/review', {draft_id: state.draft.id, destination: 'telegraph'})
    const form = document.createElement('form'); form.className = 'form'; form.innerHTML = `<label>Título<input name="title" value="${htmlEscape(state.draft.name || '')}"></label><label><input type="checkbox" name="update"> Atualizar publicação anterior quando possível</label><div class="row"><button type="button" data-cancel>Cancelar</button><button class="primary" type="submit">Publicar</button></div>`
    form.querySelector('[data-cancel]').onclick = closeModal
    form.onsubmit = async event => { event.preventDefault(); const fd = new FormData(form); try { const result = await api('/api/telegraph/publish', {draft_id: state.draft.id, revision_id: reviewed.draft_revision_id, title: fd.get('title'), update_existing: fd.get('update') === 'on', confirmed: true}); closeModal(); showBanner(result.url ? `Telegraph publicado: ${result.url}` : 'Telegraph publicado.') } catch (error) { showBanner(error.message, 'error') } }
    openModal('Publicar no Telegraph', form)
  } catch (error) { showBanner(error.message, 'error') }
}

function settingsMenu() {
  const wrap = document.createElement('div'); wrap.className = 'choice-list'
  addChoice(wrap, 'Rascunhos', () => { closeModal(); showDrafts() })
  addChoice(wrap, 'Importar .md/.txt', () => { closeModal(); fileInput.click() })
  addChoice(wrap, 'Localizar e substituir', () => { closeModal(); findReplace() })
  addChoice(wrap, 'Exportar Markdown', () => { closeModal(); exportDocument('markdown') })
  addChoice(wrap, 'Exportar TXT', () => { closeModal(); exportDocument('txt') })
  addChoice(wrap, 'Publicar no Telegraph', () => { closeModal(); publishTelegraph() })
  addChoice(wrap, 'Desfazer', () => { closeModal(); doUndo() })
  addChoice(wrap, 'Refazer', () => { closeModal(); doRedo() })
  openModal('Documento', wrap)
}

function updateNativeSend() {
  if (!mainButton) return
  try {
    mainButton.setText('Enviar')
    mainButton.show()
    if (isEmpty()) mainButton.disable(); else mainButton.enable()
  } catch (_) {}
}
function setMainProgress(active) { if (!mainButton) return; try { if (active) { mainButton.showProgress?.(); mainButton.disable() } else { mainButton.hideProgress?.(); updateNativeSend() } } catch (_) {} }

function syncBackButton() {
  if (!tg?.BackButton) return
  try { if (!modal.classList.contains('hidden') || state.view === 'preview') tg.BackButton.show(); else tg.BackButton.hide() } catch (_) {}
}
function handleBack() { if (!modal.classList.contains('hidden')) closeModal(); else if (state.view === 'preview') setView('edit'); else tg?.close?.() }

function ensureCaretVisible(element) {
  requestAnimationFrame(() => {
    const rect = element.getBoundingClientRect(); const height = Number(tg?.viewportStableHeight || window.visualViewport?.height || window.innerHeight)
    if (rect.bottom > height - 72) element.scrollIntoView({block: 'center', behavior: 'smooth'})
  })
}

function updateViewport(stableOnly = false, event = null) {
  if (stableOnly && event && event.isStateStable === false) return
  const height = Number(tg?.viewportStableHeight || window.visualViewport?.height || window.innerHeight)
  if (height) document.documentElement.style.setProperty('--stable-height', `${height}px`)
}

async function bootstrapTelegram() {
  if (!tg) return
  try {
    tg.ready(); tg.expand(); tg.enableClosingConfirmation?.(); tg.setHeaderColor?.('bg_color')
    if (tg.requestFullscreen && !tg.isFullscreen) { try { tg.requestFullscreen() } catch (_) {} }
    tg.BackButton?.onClick(handleBack)
    tg.SettingsButton?.show(); tg.SettingsButton?.onClick(settingsMenu)
    mainButton?.onClick(sendTelegram)
    tg.onEvent?.('viewportChanged', event => updateViewport(true, event))
    tg.onEvent?.('safeAreaChanged', () => updateViewport(false))
    tg.onEvent?.('contentSafeAreaChanged', () => updateViewport(false))
    updateViewport(false); syncBackButton(); updateNativeSend()
  } catch (_) {}
}

async function bootstrap() {
  await bootstrapTelegram()
  const local = localMirror()
  try {
    const data = await api('/api/bootstrap', {})
    state.destinations = data.destinations || []
    const requested = data.requested_draft || new URLSearchParams(location.search).get('draft')
    if (requested) return loadDraft(requested)
    const drafts = data.drafts || []
    if (local?.draft_id) {
      const remote = drafts.find(item => item.id === local.draft_id)
      if (remote && remote.current_revision_id && local.revision_id && remote.current_revision_id !== local.revision_id) {
        const loaded = await api('/api/draft/load', {draft_id: local.draft_id}); state.draft = loaded.draft; state.document = loaded.draft.document; return showConflict(loaded.draft)
      }
    }
    if (drafts.length) {
      const wrap = document.createElement('div'); wrap.className = 'choice-list'
      addChoice(wrap, `Continuar: ${drafts[0].name || 'último trabalho'}`, () => loadDraft(drafts[0].id))
      addChoice(wrap, 'Começar vazio', () => { setDraft(null); closeModal() })
      openModal('Abrir MDTXTRT', wrap)
      return
    }
    if (local?.document) {
      state.document = local.document; state.session = local.session || {}; render(); showBanner('Espelho local recuperado. Sincronize para continuar com histórico no servidor.')
    } else setDraft(null)
  } catch (error) {
    if (local?.document) { state.document = local.document; state.session = local.session || {}; render(); showBanner('Servidor indisponível ou sessão inválida. O espelho local foi aberto sem perda.', 'error') }
    else { setDraft(null); showBanner(error.message || 'Abra a Mini App pelo Telegram.', 'error') }
  }
}

document.addEventListener('selectionchange', updateToolbarState)
window.addEventListener('beforeunload', mirrorLocal)
window.visualViewport?.addEventListener('resize', () => updateViewport(false))
editorPane.addEventListener('scroll', () => { state.session.scroll_y = editorPane.scrollTop; mirrorLocal() }, {passive: true})
document.addEventListener('focusin', event => { if (event.target.matches?.('[contenteditable=true],textarea,input')) ensureCaretVisible(event.target) })
document.addEventListener('keydown', event => { if (event.key === 'Escape' && !modal.classList.contains('hidden')) closeModal(); if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'f') { event.preventDefault(); findReplace() } })
checkpointTimer = setInterval(() => checkpoint('checkpoint', true), CHECKPOINT_MS)

bootstrap()
})()
