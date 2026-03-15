; === Separators ===
(separator) @punctuation.delimiter

; === Directives ===
(directive) @keyword.directive
(block_directive) @keyword.directive

; === Tags ===
(tag_name) @tag
(doctype) @tag

; === Attributes ===
(attribute_name) @attribute
(special_attribute_name) @attribute.special
(attribute_value) @string

; === Template control blocks ===
(brace_block "{$" @keyword.control)
(brace_block "}" @keyword.control)
(brace_block keyword: (_) @keyword.control)

(end_brace_block "{/" @keyword.control)
(end_brace_block "}" @keyword.control)
(end_brace_block name: (_) @keyword.control)

; === Interpolation braces ===
(interpolation "{" @punctuation.bracket)
(interpolation "}" @punctuation.bracket)

; === Attribute shorthand braces ===
(attribute_shorthand "{" @punctuation.bracket)
(attribute_shorthand "}" @punctuation.bracket)

; === Spread shorthand ===
(spread_shorthand "{" @punctuation.bracket)
(spread_shorthand "**" @operator)
(spread_shorthand "}" @punctuation.bracket)

; === Comments ===
(comment) @comment

