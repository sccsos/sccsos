-- newpage-to-html.lua
-- 将 \newpage 转为 HTML 分页符（用于 PDF/WeasyPrint 流水线）
function RawBlock(el)
  if el.format == 'tex' then
    local t = el.text:gsub('^%s+', ''):gsub('%s+$', '')
    if t == '\\newpage' then
      return pandoc.RawBlock('html', '<div style="page-break-before:always;"></div>')
    end
  end
  return nil
end
