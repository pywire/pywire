; Inject Python into the frontmatter block (between the --- delimiters)
((python_content) @injection.content
 (#set! injection.language "python"))

; Inject Python into inline expressions: { expr }, {$ for expr }, {** expr }
((python_code) @injection.content
 (#set! injection.language "python"))

; Inject HTML into the template section (everything after the frontmatter)
((template_section) @injection.content
 (#set! injection.language "html"))

