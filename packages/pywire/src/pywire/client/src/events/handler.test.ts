import { describe, it, expect, vi, beforeEach } from 'vitest';
import { UnifiedEventHandler } from './handler';
import { PyWireApp } from '../index';

describe('UnifiedEventHandler', () => {
    let appMock: any;
    let handler: UnifiedEventHandler;

    beforeEach(() => {
        document.body.innerHTML = '';
        appMock = {
            sendEvent: vi.fn(),
            getConfig: vi.fn().mockReturnValue({ debug: false }),
        };
        handler = new UnifiedEventHandler(appMock as PyWireApp);
    });

    it('should register listeners on init', () => {
        const addEventListenerSpy = vi.spyOn(document, 'addEventListener');
        handler.init();
        // Check for some common events
        expect(addEventListenerSpy).toHaveBeenCalledWith('click', expect.any(Function), undefined);
        expect(addEventListenerSpy).toHaveBeenCalledWith('submit', expect.any(Function), undefined);
        expect(addEventListenerSpy).toHaveBeenCalledWith('focus', expect.any(Function), { capture: true });
    });

    it('should handle basic click events', async () => {
        document.body.innerHTML = '<button id="btn" data-on-click="handleClick">Click Me</button>';
        const btn = document.getElementById('btn')!;

        handler.init();
        btn.click();

        expect(appMock.sendEvent).toHaveBeenCalledWith('handleClick', expect.objectContaining({
            type: 'click',
            id: 'btn'
        }));
    });

    it('should support .prevent modifier', () => {
        document.body.innerHTML = '<a href="#" id="link" data-on-click="nav" data-modifiers-click="prevent">Link</a>';
        const link = document.getElementById('link')!;
        const event = new MouseEvent('click', { bubbles: true, cancelable: true });
        const preventDefaultSpy = vi.spyOn(event, 'preventDefault');

        handler.init();
        link.dispatchEvent(event);

        expect(preventDefaultSpy).toHaveBeenCalled();
        expect(appMock.sendEvent).toHaveBeenCalled();
    });

    it('should support .stop modifier', () => {
        document.body.innerHTML = '<div id="parent"><button id="child" data-on-click="hit" data-modifiers-click="stop"></button></div>';
        const child = document.getElementById('child')!;
        const event = new MouseEvent('click', { bubbles: true, cancelable: true });
        const stopPropagationSpy = vi.spyOn(event, 'stopPropagation');

        handler.init();
        child.dispatchEvent(event);

        expect(stopPropagationSpy).toHaveBeenCalled();
    });

    it('should support .self modifier', () => {
        document.body.innerHTML = `
            <div id="outer" data-on-click="outerHit" data-modifiers-click="self">
                <button id="inner">Inner</button>
            </div>
        `;
        const outer = document.getElementById('outer')!;
        const inner = document.getElementById('inner')!;

        handler.init();

        // Clicking inner should NOT trigger outer because of .self
        inner.click();
        expect(appMock.sendEvent).not.toHaveBeenCalledWith('outerHit', expect.anything());

        // Clicking outer should trigger
        outer.click();
        expect(appMock.sendEvent).toHaveBeenCalledWith('outerHit', expect.anything());
    });

    it('should support key modifiers like .enter', () => {
        document.body.innerHTML = '<input id="input" data-on-keyup="submit" data-modifiers-keyup="enter">';
        const input = document.getElementById('input')!;

        handler.init();

        // Non-enter key should not trigger
        input.dispatchEvent(new KeyboardEvent('keyup', { key: 'a', bubbles: true }));
        expect(appMock.sendEvent).not.toHaveBeenCalled();

        // Enter key should trigger
        input.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', bubbles: true }));
        expect(appMock.sendEvent).toHaveBeenCalledWith('submit', expect.objectContaining({
            type: 'keyup',
            key: 'Enter'
        }));
    });

    it('should handle .debounce modifier', async () => {
        vi.useFakeTimers();
        document.body.innerHTML = '<input id="input" data-on-input="search" data-modifiers-input="debounce">';
        const input = document.getElementById('input')!;

        handler.init();

        // First input
        input.dispatchEvent(new Event('input', { bubbles: true }));
        expect(appMock.sendEvent).not.toHaveBeenCalled();

        // Second input quickly
        input.dispatchEvent(new Event('input', { bubbles: true }));

        // Wait for debounce (default 250ms)
        vi.advanceTimersByTime(300);

        expect(appMock.sendEvent).toHaveBeenCalledTimes(1);
        vi.useRealTimers();
    });

    it('should extract input value', () => {
        document.body.innerHTML = '<input id="input" value="hello" data-on-change="save">';
        const input = document.getElementById('input')!;

        handler.init();
        input.dispatchEvent(new Event('change', { bubbles: true }));

        expect(appMock.sendEvent).toHaveBeenCalledWith('save', expect.objectContaining({
            value: 'hello'
        }));
    });

    it('should handle form submit and extract data', async () => {
        document.body.innerHTML = `
            <form id="form" data-on-submit="send">
                <input name="user" value="alice">
                <input name="pass" value="secret">
            </form>
        `;
        const form = document.getElementById('form')!;

        handler.init();
        form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));

        expect(appMock.sendEvent).toHaveBeenCalledWith('send', expect.objectContaining({
            type: 'submit',
            formData: {
                user: 'alice',
                pass: 'secret'
            }
        }));
    });

    it('should handle .throttle modifier', async () => {
        vi.useFakeTimers();
        document.body.innerHTML = '<button id="btn" data-on-click="fire" data-modifiers-click="throttle"></button>';
        const btn = document.getElementById('btn')!;

        handler.init();

        // First click - immediate
        btn.click();
        expect(appMock.sendEvent).toHaveBeenCalledTimes(1);

        // Second click quickly - ignored
        btn.click();
        expect(appMock.sendEvent).toHaveBeenCalledTimes(1);

        // Wait for throttle (default 250ms)
        vi.advanceTimersByTime(300);

        // Third click - works again
        btn.click();
        expect(appMock.sendEvent).toHaveBeenCalledTimes(2);
        vi.useRealTimers();
    });

    it('should support system modifiers like .shift.ctrl', () => {
        document.body.innerHTML = '<button id="btn" data-on-click="hit" data-modifiers-click="shift ctrl"></button>';
        const btn = document.getElementById('btn')!;
        handler.init();

        // Click without modifiers - no trigger
        btn.dispatchEvent(new MouseEvent('click', { bubbles: true }));
        expect(appMock.sendEvent).not.toHaveBeenCalled();

        // Click with only shift - no trigger
        btn.dispatchEvent(new MouseEvent('click', { bubbles: true, shiftKey: true }));
        expect(appMock.sendEvent).not.toHaveBeenCalled();

        // Click with BOTH shift and ctrl - trigger
        btn.dispatchEvent(new MouseEvent('click', { bubbles: true, shiftKey: true, ctrlKey: true }));
        expect(appMock.sendEvent).toHaveBeenCalled();
    });

    it('should support .window modifier', () => {
        document.body.innerHTML = '<div data-on-click="winHit" data-modifiers-click="window"></div>';
        handler.init();

        // Click anywhere (document.body)
        document.body.click();
        expect(appMock.sendEvent).toHaveBeenCalledWith('winHit', expect.anything());
    });

    it('should support .outside modifier', () => {
        document.body.innerHTML = `
            <div id="modal" data-on-click="close" data-modifiers-click="outside">
                <button id="inside">Inside</button>
            </div>
            <button id="outside">Outside</button>
        `;
        const inside = document.getElementById('inside')!;
        const outside = document.getElementById('outside')!;
        handler.init();

        // Clicking inside should NOT trigger
        inside.click();
        expect(appMock.sendEvent).not.toHaveBeenCalled();

        // Clicking outside should trigger
        outside.click();
        expect(appMock.sendEvent).toHaveBeenCalledWith('close', expect.anything());
    });

    it('should handle dynamic delegation', () => {
        handler.init();

        // Add element AFTER init
        const div = document.createElement('div');
        div.innerHTML = '<button id="dyn" data-on-click="dynamic">Dyn</button>';
        document.body.appendChild(div);

        const btn = document.getElementById('dyn')!;
        btn.click();

        expect(appMock.sendEvent).toHaveBeenCalledWith('dynamic', expect.anything());
    });

    it('should support multiple handlers via JSON', () => {
        document.body.innerHTML = `
            <button id="multi" 
                data-on-click='[{"handler": "foo", "modifiers": ["stop"]}, {"handler": "bar", "modifiers": ["prevent"]}]'
            ></button>
        `;
        const btn = document.getElementById('multi')!;
        const event = new MouseEvent('click', { bubbles: true, cancelable: true });
        const stopPropagationSpy = vi.spyOn(event, 'stopPropagation');
        const preventDefaultSpy = vi.spyOn(event, 'preventDefault');

        handler.init();
        btn.dispatchEvent(event);

        expect(appMock.sendEvent).toHaveBeenCalledWith('foo', expect.anything());
        expect(appMock.sendEvent).toHaveBeenCalledWith('bar', expect.anything());
        expect(stopPropagationSpy).toHaveBeenCalled();
        expect(preventDefaultSpy).toHaveBeenCalled();
    });

    it('should handle explicit arguments in JSON handlers', () => {
        document.body.innerHTML = `
            <button id="args" 
                data-on-click='[{"handler": "save", "modifiers": [], "args": [1, "test"]}]'
            ></button>
        `;
        const btn = document.getElementById('args')!;

        handler.init();
        btn.click();

        expect(appMock.sendEvent).toHaveBeenCalledWith('save', expect.objectContaining({
            args: {
                arg0: 1,
                arg1: 'test'
            }
        }));
    });

    it('should fallback to e.code for key modifiers', () => {
        document.body.innerHTML = '<input id="input" data-on-keyup="hit" data-modifiers-keyup="h">';
        const input = document.getElementById('input')!;

        handler.init();

        // Simulate Alt+H which might produce '˙' but has code 'KeyH'
        input.dispatchEvent(new KeyboardEvent('keyup', { key: '˙', code: 'KeyH', bubbles: true }));

        expect(appMock.sendEvent).toHaveBeenCalledWith('hit', expect.anything());
    });
});
