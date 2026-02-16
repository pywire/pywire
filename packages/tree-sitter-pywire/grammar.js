module.exports = grammar({
    name: 'pywire',

    extras: $ => [
        $.comment,
        /[ \t\r\n]/
    ],

    conflicts: $ => [
        [$.tag, $.self_closing_tag],
        [$._python_code]
    ],

    rules: {
        source_file: $ => seq(
            optional($.directives_section),
            optional($.frontmatter),
            optional($.template_section)
        ),

        directives_section: $ => repeat1(choice(
            $.directive,
            $.block_directive
        )),

        directive: $ => token(prec(100, seq(
            '!',
            /[a-zA-Z_]\w*/,
            /[^\n\r]*/,
            /\r?\n/
        ))),

        block_directive: $ => token(prec(101, seq(
            '!',
            /[a-zA-Z_]\w*/,
            /[ \t]*/,
            '{',
            repeat(choice(
                /[^{}]/,
                /\r?\n/,
                seq('{', repeat(choice(/[^{}]/, /\r?\n/)), '}')
            )),
            '}',
            optional(/\n/) // Allow but don't require newline after block
        ))),

        frontmatter: $ => seq(
            $.separator,
            optional(alias($._python_content, $.python_content)),
            $.separator
        ),

        separator: $ => token(/---[ \t]*\r?\n/),

        _python_content: $ => repeat1(choice(
            /[^-\n\r]+/,
            /\r?\n/,
            seq('-', /[^-\n\r]*/),
            seq('--', /[^-\n\r]*/)
        )),

        template_section: $ => repeat1($._html_content),

        _directive_brace_content: $ => repeat1(choice(
            /[^{}\n\r]+/,
            /\r?\n/,
            seq('{', optional($._directive_brace_content), '}')
        )),

        _html_content: $ => choice(
            $.tag,
            $.self_closing_tag,
            $.void_tag,
            $.script_tag,
            $.style_tag,
            $.text,
            prec(10, $.brace_block),
            prec(5, $.end_brace_block),
            prec(1, $.interpolation),
            $.doctype,
            $.hyphen,
            $.bang
        ),

        doctype: $ => /<!DOCTYPE[^>]*>/i,

        tag: $ => seq(
            '<',
            field('name', $.tag_name),
            repeat($.attribute),
            '>',
            repeat($._html_content),
            '</',
            field('close_name', $.tag_name),
            '>'
        ),

        self_closing_tag: $ => seq(
            '<',
            field('name', $.tag_name),
            repeat($.attribute),
            '/>'
        ),

        void_tag: $ => seq(
            '<',
            field('name', choice(
                'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
                'link', 'meta', 'param', 'source', 'track', 'wbr'
            )),
            repeat($.attribute),
            choice('>', '/>')
        ),

        script_tag: $ => seq(
            '<script',
            repeat($.attribute),
            '>',
            optional(alias($._script_content, $.text)),
            '</script>'
        ),

        style_tag: $ => seq(
            '<style',
            repeat($.attribute),
            '>',
            optional(alias($._style_content, $.text)),
            '</style>'
        ),

        _script_content: $ => repeat1(choice(
            /[^<]+/,
            seq('<', /[^/]/)
        )),

        _style_content: $ => repeat1(choice(
            /[^<]+/,
            seq('<', /[^/]/)
        )),

        tag_name: $ => /[^ />{}"'=!\n\r]+/,

        attribute: $ => choice(
            seq(
                field('name', choice($.attribute_name, $.special_attribute_name)),
                optional(seq(
                    '=',
                    field('value', choice(
                        $.attribute_value,
                        $.interpolation
                    ))
                ))
            ),
            $.attribute_shorthand,
            $.spread_shorthand
        ),

        attribute_shorthand: $ => seq(
            '{',
            field('name', $.attribute_name),
            '}'
        ),

        spread_shorthand: $ => seq(
            '{',
            '**',
            field('expr', alias($._python_code, $.python_code)),
            '}'
        ),

        attribute_name: $ => token(seq(
            /[^ />{}"'=!\n\r]+/,
        )),

        special_attribute_name: $ => token(prec(10, seq(
            choice(
                '@',
                // '$', // Removed: value accessor shorthand is gone
                ':',
                '**'
            ),
            /[a-zA-Z_][\w.\-]*/
        ))),

        attribute_value: $ => choice(
            seq('"', /[^"]*/, '"'),
            seq("'", /[^']*/, "'"),
            /[^ />{}"'=\n\r]+/
        ),

        text: $ => prec(1, /[^<{}! \t\n\r\-][^<{}\n\r\-]*/),

        interpolation: $ => seq(
            '{',
            field('expr', alias($._python_code, $.python_code)),
            '}'
        ),

        brace_block: $ => seq(
            '{$',
            field('keyword', $.block_keyword),
            optional(field('expression', alias($._python_code, $.python_code))),
            '}'
        ),

        end_brace_block: $ => seq(
            '{/',
            field('name', alias(/[a-z]+/, $.block_keyword)),
            '}'
        ),

        block_keyword: $ => choice(
            'if', 'for', 'try', 'await', 'elif', 'else', 'finally', 'except', 'then', 'catch', 'html'
        ),

        _python_code: $ => repeat1(choice(
            /[^{}]+/,
            seq('{', optional($._python_code), '}')
        )),

        comment: $ => /<!--[^-]*(-[^-]+)*-->/,
        hyphen: $ => '-',
        bang: $ => '!',
    }
});
