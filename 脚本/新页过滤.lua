-- newpage-to-docx.lua
-- 将 \newpage 转为 DOCX 分页符
-- 用于 pandoc --lua-filter=newpage-to-docx.lua
--
-- pandoc 将 \newpage 解析为 RawBlock format='tex'，文本内容为 "\newpage"（单反斜杠）

function RawBlock(el)
  if el.format == 'tex' then
    local t = el.text:gsub('^%s+', ''):gsub('%s+$', '')
    if t == '\\newpage' then
      return pandoc.RawBlock('openxml',
        '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'
      )
    end
  end
  return nil
end
