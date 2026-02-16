(tag_name) @tag
(attribute_name) @attribute
(special_attribute_name) @constructor
(directive) @keyword
(block_directive) @keyword
(comment) @comment

(brace_block "{$" @keyword)
(brace_block "}" @keyword)
(brace_block keyword: (_) @keyword)

(end_brace_block "{/" @keyword)
(end_brace_block "}" @keyword)
(end_brace_block name: (_) @keyword)

(python_code) @embedded.python

