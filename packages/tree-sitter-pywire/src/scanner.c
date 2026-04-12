#include "tree_sitter/parser.h"
#include <stdbool.h>

enum TokenType {
    SEPARATOR,
    PYTHON_CONTENT,
};

void *tree_sitter_pywire_external_scanner_create(void) { return NULL; }
void tree_sitter_pywire_external_scanner_destroy(void *payload) {}
unsigned tree_sitter_pywire_external_scanner_serialize(void *payload,
                                                       char *buffer) {
    return 0;
}
void tree_sitter_pywire_external_scanner_deserialize(void *payload,
                                                      const char *buffer,
                                                      unsigned length) {}

/* Match ---[ \t]*(\r?\n|EOF) starting at column 0. Advances the lexer
 * on success. On failure, some characters may have been consumed. */
static bool scan_separator(TSLexer *lexer) {
    if (lexer->get_column(lexer) != 0) return false;
    if (lexer->lookahead != '-') return false;
    lexer->advance(lexer, false);
    if (lexer->lookahead != '-') return false;
    lexer->advance(lexer, false);
    if (lexer->lookahead != '-') return false;
    lexer->advance(lexer, false);

    while (lexer->lookahead == ' ' || lexer->lookahead == '\t') {
        lexer->advance(lexer, false);
    }

    if (lexer->lookahead == '\n') {
        lexer->advance(lexer, false);
        lexer->mark_end(lexer);
        lexer->result_symbol = SEPARATOR;
        return true;
    }
    if (lexer->lookahead == '\r') {
        lexer->advance(lexer, false);
        if (lexer->lookahead == '\n') lexer->advance(lexer, false);
        lexer->mark_end(lexer);
        lexer->result_symbol = SEPARATOR;
        return true;
    }
    if (lexer->eof(lexer)) {
        lexer->mark_end(lexer);
        lexer->result_symbol = SEPARATOR;
        return true;
    }
    return false;
}

/* Check if we're looking at --- at column 0 (potential separator).
 * Advances the lexer past 1-2 dashes to peek. Caller must have already
 * set mark_end before calling this. */
static bool at_triple_dash(TSLexer *lexer) {
    /* Caller verified c == '-' and column == 0 */
    lexer->advance(lexer, false);
    if (lexer->lookahead != '-') return false;
    lexer->advance(lexer, false);
    return lexer->lookahead == '-';
}

bool tree_sitter_pywire_external_scanner_scan(void *payload, TSLexer *lexer,
                                               const bool *valid_symbols) {
    bool want_separator = valid_symbols[SEPARATOR];
    bool want_python = valid_symbols[PYTHON_CONTENT];

    if (!want_separator && !want_python) return false;

    /* When only SEPARATOR is needed, match directly. */
    if (want_separator && !want_python) {
        return scan_separator(lexer);
    }

    /* PYTHON_CONTENT is valid (possibly alongside SEPARATOR).
     *
     * Scan Python content character by character, tracking string and
     * comment state. When we encounter --- at column 0 outside strings
     * and comments, stop: that's a separator boundary.
     *
     * If we consumed content before the boundary → return PYTHON_CONTENT
     * If nothing consumed (empty frontmatter) → return false and let
     * tree-sitter retry for SEPARATOR in a new scan call.
     */
    bool consumed = false;

    bool in_triple_double = false;
    bool in_triple_single = false;
    bool in_double = false;
    bool in_single = false;
    bool in_comment = false;

    #define IN_STRING (in_triple_double || in_triple_single || in_double || in_single)

    while (!lexer->eof(lexer)) {
        int32_t c = lexer->lookahead;

        /* At column 0, outside any string or comment, starting with '-':
         * check if this is --- (potential separator). */
        if (lexer->get_column(lexer) == 0 && !IN_STRING && !in_comment && c == '-') {
            /* Mark the token end BEFORE the dashes. Tree-sitter will
             * re-lex from this position for the next token. */
            lexer->mark_end(lexer);

            if (at_triple_dash(lexer)) {
                /* Three dashes at column 0 outside strings — separator. */
                if (consumed) {
                    lexer->result_symbol = PYTHON_CONTENT;
                    return true;
                }
                /* Empty frontmatter — return false so tree-sitter retries
                 * with SEPARATOR (scan_separator handles it). */
                return false;
            }
            /* Fewer than 3 dashes — regular python content. The lexer
             * advanced past 1-2 chars; continue scanning from there. */
            consumed = true;
            continue;
        }

        consumed = true;

        /* Newline handling */
        if (c == '\n' || c == '\r') {
            in_comment = false;
            in_double = false;
            in_single = false;

            lexer->advance(lexer, false);
            if (c == '\r' && lexer->lookahead == '\n') {
                lexer->advance(lexer, false);
            }
            lexer->mark_end(lexer);
            continue;
        }

        /* Inside a comment — consume until newline */
        if (in_comment) {
            lexer->advance(lexer, false);
            continue;
        }

        /* Escape sequences inside strings */
        if (IN_STRING && c == '\\') {
            lexer->advance(lexer, false);
            if (!lexer->eof(lexer)) {
                lexer->advance(lexer, false);
            }
            continue;
        }

        /* Triple-double-quoted string */
        if (in_triple_double) {
            if (c == '"') {
                lexer->advance(lexer, false);
                if (lexer->lookahead == '"') {
                    lexer->advance(lexer, false);
                    if (lexer->lookahead == '"') {
                        lexer->advance(lexer, false);
                        in_triple_double = false;
                        continue;
                    }
                }
                continue;
            }
            lexer->advance(lexer, false);
            continue;
        }

        /* Triple-single-quoted string */
        if (in_triple_single) {
            if (c == '\'') {
                lexer->advance(lexer, false);
                if (lexer->lookahead == '\'') {
                    lexer->advance(lexer, false);
                    if (lexer->lookahead == '\'') {
                        lexer->advance(lexer, false);
                        in_triple_single = false;
                        continue;
                    }
                }
                continue;
            }
            lexer->advance(lexer, false);
            continue;
        }

        /* Single-line double-quoted string */
        if (in_double) {
            if (c == '"') {
                lexer->advance(lexer, false);
                in_double = false;
                continue;
            }
            lexer->advance(lexer, false);
            continue;
        }

        /* Single-line single-quoted string */
        if (in_single) {
            if (c == '\'') {
                lexer->advance(lexer, false);
                in_single = false;
                continue;
            }
            lexer->advance(lexer, false);
            continue;
        }

        /* Outside strings — check for string openers */
        int32_t quote_char = 0;
        if (c == '"' || c == '\'') {
            quote_char = c;
            lexer->advance(lexer, false);
        } else if (c == 'r' || c == 'R' || c == 'b' || c == 'B' ||
                   c == 'f' || c == 'F' || c == 'u' || c == 'U') {
            lexer->advance(lexer, false);
            int32_t next = lexer->lookahead;
            if (next == '"' || next == '\'') {
                quote_char = next;
                lexer->advance(lexer, false);
            } else if ((c == 'r' || c == 'R' || c == 'b' || c == 'B' ||
                         c == 'f' || c == 'F') &&
                        (next == 'b' || next == 'B' || next == 'r' || next == 'R' ||
                         next == 'f' || next == 'F')) {
                lexer->advance(lexer, false);
                next = lexer->lookahead;
                if (next == '"' || next == '\'') {
                    quote_char = next;
                    lexer->advance(lexer, false);
                }
            }
            if (!quote_char) continue;
        } else if (c == '#') {
            in_comment = true;
            lexer->advance(lexer, false);
            continue;
        } else {
            lexer->advance(lexer, false);
            continue;
        }

        /* We have a quote_char and the lexer is positioned after it */
        if (lexer->lookahead == quote_char) {
            lexer->advance(lexer, false);
            if (lexer->lookahead == quote_char) {
                lexer->advance(lexer, false);
                if (quote_char == '"') {
                    in_triple_double = true;
                } else {
                    in_triple_single = true;
                }
                continue;
            }
            /* Empty string (two quotes) */
            continue;
        }
        if (quote_char == '"') {
            in_double = true;
        } else {
            in_single = true;
        }
    }

    if (consumed) {
        lexer->mark_end(lexer);
        lexer->result_symbol = PYTHON_CONTENT;
        return true;
    }
    return false;

    #undef IN_STRING
}
