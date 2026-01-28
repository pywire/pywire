module.exports = grammar({
    name: 'pywire',

    extras: $ => [
        $.comment,
        /\s+/
    ],

    rules: {
        source_file: $ => repeat(choice(
            $.directive,
            $._html_content,
            $.python_section
        )),

        // Directives: !path, !layout, etc.
        directive: $ => choice(
            $._directive_single_line,
            $._directive_multiline
        ),

        _directive_single_line: $ => seq(
            alias(token(seq('!', /[a-zA-Z_]\w*/)), $.keyword_directive),
            optional($._directive_content),
            /\r?\n/
        ),

        _directive_content: $ => token(prec(-1, /.+/)),

        _directive_multiline: $ => seq(
            alias('!path', $.keyword_directive),
            '{',
            repeat(alias($._directive_multiline_content, $.python_code)),
            '}'
        ),

        _directive_multiline_content: $ => /[^}]+/,

        // Python Section
        python_section: $ => seq(
            $.separator,
            optional(alias($._python_block, $.python_code))
        ),

        _python_block: $ => token(prec(1, repeat1(/.|\n/))),

        // HTML Content (Simplified for now)
        _html_content: $ => choice(
            $.tag,
            $.text,
            $.hyphen,
            $.interpolation
        ),

        tag: $ => seq(
            '<',
            alias($.tag_name, $.tag_name),
            repeat($.attribute),
            '>',
            repeat($._html_content),
            '</',
            alias($.tag_name, $.tag_name),
            '>'
        ),

        tag_name: $ => /\w+/,

        attribute: $ => seq(
            $._attribute_name,
            optional(seq(
                '=',
                $.attribute_value
            ))
        ),

        _attribute_name: $ => choice(
            alias(/\w+/, $.attribute_name),
            alias(choice(/@[\w.]+/, /\$[a-zA-Z_]\w*/, /:\w+/), $.special_attribute_name)
        ),

        attribute_value: $ => choice(
            seq('"', alias(/[^"]*/, $.attribute_content), '"'),
            seq("'", alias(/[^']*/, $.attribute_content), "'")
        ),

        interpolation: $ => seq(
            '{',
            alias($._interpolation_content, $.python_code),
            '}'
        ),

        _interpolation_content: $ => /[^}]+/,

        // Separator must be on its own line (roughly)
        separator: $ => token(seq(
            '---'
        )),

        // ...

        text: $ => /[^<{}\-]+/,
        hyphen: $ => '-',

        comment: $ => token(seq('<!--', /[^-]+/, '-->'))
    }
});
