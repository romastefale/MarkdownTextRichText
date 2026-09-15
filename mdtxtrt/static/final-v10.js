/* Third verification: preserve canonical Rich HTML in editable table cells. */
renderTable = function renderTableFinal(block, node) {
  const wrap = document.createElement('div'); wrap.className = 'table-wrap'
  const table = document.createElement('table'); table.className = 'rich-table'
  const rows = node.rows || (node.rows = [['', ''], ['', '']])
  rows.forEach((row, r) => {
    const tr = document.createElement('tr')
    row.forEach((cell, c) => {
      const value = typeof cell === 'object' && cell !== null ? cell : {text: cell}
      const td = document.createElement(value.header || r === 0 ? 'th' : 'td')
      td.contentEditable = 'true'
      if (value.html != null) td.innerHTML = value.html
      else td.textContent = value.text || ''
      td.oninput = () => {
        const next = Object.assign({}, value, {html: td.innerHTML})
        delete next.text
        rows[r][c] = next
        markDirty('edit')
      }
      td.onfocus = () => selectBlock(block)
      td.addEventListener('keyup', rememberSelection)
      td.addEventListener('mouseup', rememberSelection)
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
