module.exports = grammar({
    name: 'pywire',

    extras: $ => [
        $.comment,
        /\s+/
    ],

    rules: {
        source_file: $ => choice(
            seq(
                repeat(choice(
                    $.directive,
                    $.python_line,
                    /\r?\n/
                )),
                $.separator,
                repeat(choice(
                    $._html_content,
                    /\r?\n/
                ))
            ),
            repeat(choice(
                $.directive,
                $._html_content,
                /\r?\n/
            ))
        ),

        // Directives: !path, !layout, etc.
        directive: $ => prec(1, choice(
            $._directive_single_line,
            $._directive_multiline
        )),

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

        // Python Header Lines (before separator)
        python_line: $ => token(prec(1, /[^\n]+/)),

        // HTML Content (Simplified for now)
        _html_content: $ => choice(
            $.tag,
            $.self_closing_tag,
            $.text,
            $.hyphen,
            $.interpolation,
            $.brace_block,
            $.end_brace_block
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

        self_closing_tag: $ => seq(
            '<',
            alias($.tag_name, $.tag_name),
            repeat($.attribute),
            '/>'
        ),

        tag_name: $ => /[a-zA-Z0-9_$-]+/,

        attribute: $ => choice(
            seq(
                $._attribute_name,
                optional(seq(
                    '=',
                    $.attribute_value
                ))
            ),
            $.interpolation
        ),

        _attribute_name: $ => choice(
            alias(/\w+/, $.attribute_name),
            alias(choice(/@[\w.]+/, /\$[a-zA-Z_]\w*/, /:\w+/), $.special_attribute_name)
        ),

        attribute_value: $ => choice(
            seq('"', alias(/[^"]*/, $.attribute_content), '"'),
            seq("'", alias(/[^']*/, $.attribute_content), "'"),
            $.interpolation
        ),

        interpolation: $ => seq(
            '{',
            alias($._interpolation_content, $.python_code),
            '}'
        ),

        _interpolation_content: $ => /[^}]+/,

        brace_block: $ => seq(
            '{',
            '$',
            alias(choice('if', 'elif', 'else', 'for', 'await', 'then', 'catch', 'try', 'except', 'finally', 'html'), $.keyword_control),
            optional(alias($._python_code, $.python_code)),
            '}'
        ),

        end_brace_block: $ => seq(
            '{',
            '/',
            alias(choice('if', 'for', 'await', 'try'), $.keyword_control),
            '}'
        ),

        _python_code: $ => /[^}]+/,

        // Separator must be on its own line (roughly)
        separator: $ => token(seq(
            /-{3,}/,
            /\s*/,
            /[Hh][Tt][Mm][Ll]/,
            /\s*/,
            /-{3,}/
        )),

        // ...

        text: $ => /[^<{}\-!]+|!/,
        hyphen: $ => '-',

        comment: $ => token(seq('<!--', /[^-]+/, '-->'))
    }
});
