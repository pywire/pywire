import * as vscode from 'vscode';
import { TreeSitterService } from './TreeSitterService';
import { Parser } from 'web-tree-sitter';
type SyntaxNode = any; // TODO: Fix type

// Legend must match the classification we use
export const tokenTypesLegend = [
    'keyword', 'variable', 'string', 'function', 'class', 'method', 'comment',
    'type', 'parameter', 'property', 'operator', 'decorator', 'macro'
];

export const tokenModifiersLegend = [
    'declaration', 'documentation', 'readonly', 'static', 'abstract', 'async'
];

export const legend = new vscode.SemanticTokensLegend(tokenTypesLegend, tokenModifiersLegend);

export class PyWireSemanticTokenProvider implements vscode.DocumentSemanticTokensProvider {
    constructor(private treeSitterService: TreeSitterService) { }

    async provideDocumentSemanticTokens(
        document: vscode.TextDocument,
        token: vscode.CancellationToken
    ): Promise<vscode.SemanticTokens> {
        const tree = this.treeSitterService.parse(document.getText());
        if (!tree) {
            return new vscode.SemanticTokens(new Uint32Array(0));
        }

        const builder = new vscode.SemanticTokensBuilder(legend);
        this.visitNode(tree.rootNode, builder);

        return builder.build();
    }

    private visitNode(node: SyntaxNode, builder: vscode.SemanticTokensBuilder) {
        const type = node.type;

        if (type === 'tag_name') {
            this.addToken(node, 'class', builder);
        } else if (type === 'attribute_name') {
            this.addToken(node, 'property', builder);
        } else if (type === 'special_attribute_name') {
            this.addToken(node, 'macro', builder);
        } else if (type === 'attribute_content') {
            // Check if this is a special attribute
            const isSpecial = node.parent?.parent?.children.some((c: any) => c.type === 'special_attribute_name');
            if (isSpecial) {
                this.addToken(node, 'variable', builder);
            }
        } else if (type === 'keyword_directive') {
            this.addToken(node, 'keyword', builder);
        } else if (type === 'python_code') {
            this.addToken(node, 'variable', builder);
        } else if (type === 'comment') {
            this.addToken(node, 'comment', builder);
        } else if (type === 'separator') {
            this.addToken(node, 'keyword', builder);
        }

        for (const child of node.children) {
            this.visitNode(child, builder);
        }
    }

    private addToken(node: SyntaxNode, tokenType: string, builder: vscode.SemanticTokensBuilder) {
        // Tree-sitter uses 0-indexed rows/cols. VS Code does too.
        // We need to map node position to range
        // If node spans multiple lines, token builder usually expects single line tokens?
        // VS Code SemanticTokensBuilder can handle multiline? No, tokens are usually single line.
        // But let's assume simple nodes for now.

        // Actually, builder.push(range, type, modifiers) handles multiline? 
        // Docs say: "The range of the token. ... Must be single-line."
        // So we must verify.

        if (node.startPosition.row === node.endPosition.row) {
            const range = new vscode.Range(
                new vscode.Position(node.startPosition.row, node.startPosition.column),
                new vscode.Position(node.endPosition.row, node.endPosition.column)
            );
            builder.push(range, tokenType);
        } else {
            // Handle multiline nodes if necessary, or just skip/highlight start
        }
    }
}
