use euclid::{Point2D, Rect, Scale, Size2D};
use raw_window_handle::{HasDisplayHandle, HasWindowHandle};
use std::cell::Cell;
use std::env;
use std::ffi::CStr;
use std::fs;
use std::os::raw::c_char;
use std::path::PathBuf;
use std::rc::Rc;
use std::sync::Arc;
use url::Url;
use winit::application::ApplicationHandler;
use winit::event::{ElementState, MouseButton, MouseScrollDelta, WindowEvent};
use winit::event_loop::{ActiveEventLoop, ControlFlow, EventLoop, EventLoopProxy};
use winit::window::{CursorIcon, Window, WindowAttributes, WindowId};

#[cfg(target_os = "macos")]
use {
    objc2_app_kit::{NSColorSpace, NSMenu, NSMenuItem, NSView},
    objc2_foundation::{MainThreadMarker, NSString},
};

use servo::{
    resources::{self, Resource, ResourceReaderMethods},
    ConsoleLogLevel, ContextMenu, ContextMenuAction, Cursor, DevicePixel, DevicePoint,
    EditingActionEvent, EmbedderControl, EventLoopWaker, InputEvent, InputEventId,
    InputEventResult, LoadStatus, MouseButton as ServoMouseButton, MouseButtonAction,
    MouseButtonEvent, MouseMoveEvent, OffscreenRenderingContext, RenderingContext, Servo,
    ServoBuilder, WebView, WebViewBuilder, WebViewDelegate, WheelDelta, WheelEvent, WheelMode,
    WindowRenderingContext,
};

mod keyutils;
use keyutils::keyboard_event_from_winit;

#[derive(Debug)]
enum UserEvent {
    Wake,
    ExecuteJs(String),
    SetTitle(String),
    Resize(u32, u32),
}

static mut ON_EVENT_CALLBACK: Option<extern "C" fn(*const c_char)> = None;
static PROXY: std::sync::OnceLock<EventLoopProxy<UserEvent>> = std::sync::OnceLock::new();

#[repr(C)]
pub struct InitParams {
    pub title: *const c_char,
    pub url: *const c_char,
    pub width: u32,
    pub height: i32,
    pub on_event: Option<extern "C" fn(*const c_char)>,
}

struct JsonWaker {
    proxy: EventLoopProxy<UserEvent>,
}

impl EventLoopWaker for JsonWaker {
    fn clone_box(&self) -> Box<dyn EventLoopWaker> {
        Box::new(JsonWaker {
            proxy: self.proxy.clone(),
        })
    }
    fn wake(&self) {
        let _ = self.proxy.send_event(UserEvent::Wake);
    }
}

struct PyWireResourceReader {
    path: PathBuf,
}

impl ResourceReaderMethods for PyWireResourceReader {
    fn read(&self, res: Resource) -> Vec<u8> {
        let mut path = self.path.clone();
        path.push(res.filename());
        match fs::read(&path) {
            Ok(bytes) => bytes,
            Err(e) => {
                eprintln!(
                    "[pw_servo] Error reading resource {:?} from {:?}: {}",
                    res.filename(),
                    path,
                    e
                );
                vec![]
            }
        }
    }
    fn sandbox_access_files(&self) -> Vec<PathBuf> {
        vec![]
    }
    fn sandbox_access_files_dirs(&self) -> Vec<PathBuf> {
        vec![self.path.clone()]
    }
}

struct PyWireWebViewDelegate {
    window: Arc<Window>,
    needs_repaint: Rc<Cell<bool>>,
}

impl PyWireWebViewDelegate {
    #[cfg(target_os = "macos")]
    fn show_native_context_menu(&self, mtm: MainThreadMarker, menu: ContextMenu) {
        let window_handle = self
            .window
            .window_handle()
            .expect("Failed to get window handle");
        if let raw_window_handle::RawWindowHandle::AppKit(handle) = window_handle.as_raw() {
            unsafe {
                let view_ptr = handle.ns_view.as_ptr() as *mut NSView;
                if view_ptr.is_null() {
                    menu.dismiss();
                    return;
                }
                let view = &*view_ptr;

                // Get position from Servo's context menu data.
                let pos = menu.position();
                // Convert from DevicePixels (Servo) to Logical Points (AppKit).
                let scale = self.window.scale_factor();
                let logical_x = pos.min.x as f64 / scale;
                let logical_y = pos.min.y as f64 / scale;

                // winit's content view on macOS is typically flipped (0,0 at top-left),
                // so we don't need the view_height - y flip.
                let ns_point = objc2_foundation::NSPoint::new(logical_x, logical_y);

                println!(
                    "[pw_servo] Context menu: pos=({:?}), scale={}, ns_point=({}, {})",
                    pos, scale, ns_point.x, ns_point.y
                );

                let ns_menu = NSMenu::new(mtm);
                ns_menu.setAutoenablesItems(false);

                // Tag constants for menu items
                const TAG_BACK: isize = 1;
                const TAG_FORWARD: isize = 2;
                const TAG_RELOAD: isize = 3;
                const TAG_COPY: isize = 4;
                const TAG_PASTE: isize = 5;

                let add_item = |title: &str, tag: isize, key: &str| {
                    let title = NSString::from_str(title);
                    let key = NSString::from_str(key);
                    let item = NSMenuItem::initWithTitle_action_keyEquivalent(
                        mtm.alloc::<NSMenuItem>(),
                        &title,
                        None, // no action selector — we use tags
                        &key,
                    );
                    item.setTag(tag);
                    item.setEnabled(true);
                    ns_menu.addItem(&item);
                };

                add_item("Back", TAG_BACK, "");
                add_item("Forward", TAG_FORWARD, "");
                add_item("Reload", TAG_RELOAD, "");
                ns_menu.addItem(&NSMenuItem::separatorItem(mtm));
                add_item("Copy", TAG_COPY, "");
                add_item("Paste", TAG_PASTE, "");

                // popUpMenuPositioningItem:atLocation:inView: is SYNCHRONOUS.
                // It blocks until the user selects an item or dismisses the menu.
                let selected =
                    ns_menu.popUpMenuPositioningItem_atLocation_inView(None, ns_point, Some(view));

                if selected {
                    // Check which item was highlighted (the last item the user selected)
                    if let Some(item) = ns_menu.highlightedItem() {
                        let tag = item.tag();
                        match tag {
                            TAG_BACK => menu.select(ContextMenuAction::GoBack),
                            TAG_FORWARD => menu.select(ContextMenuAction::GoForward),
                            TAG_RELOAD => menu.select(ContextMenuAction::Reload),
                            TAG_COPY => menu.select(ContextMenuAction::Copy),
                            TAG_PASTE => menu.select(ContextMenuAction::Paste),
                            _ => menu.dismiss(),
                        }
                    } else {
                        menu.dismiss();
                    }
                } else {
                    menu.dismiss();
                }
            }
        } else {
            menu.dismiss();
        }
    }
}

impl WebViewDelegate for PyWireWebViewDelegate {
    fn show_console_message(&self, _webview: WebView, level: ConsoleLogLevel, message: String) {
        // Intercept PW_MSG: prefix for JS -> Python bridge
        if let Some(payload) = message.strip_prefix("PW_MSG:") {
            unsafe {
                if let Some(cb) = ON_EVENT_CALLBACK {
                    use std::ffi::CString;
                    if let Ok(c_payload) = CString::new(payload) {
                        cb(c_payload.as_ptr());
                    }
                }
            }
        } else {
            println!("[console] {:?}: {}", level, message);
        }
    }

    fn notify_new_frame_ready(&self, _webview: WebView) {
        // println!("[pw_servo] New frame ready, requesting redraw");
        self.needs_repaint.set(true);
        self.window.request_redraw();
    }

    fn notify_load_status_changed(&self, _webview: WebView, status: LoadStatus) {
        println!("[pw_servo] Load status changed: {:?}", status);
        self.window.request_redraw();
    }

    fn notify_cursor_changed(&self, _webview: WebView, cursor: Cursor) {
        // println!("[pw_servo] Cursor changed: {:?}", cursor);
        match cursor {
            Cursor::Default => self.window.set_cursor(CursorIcon::Default),
            Cursor::Pointer => self.window.set_cursor(CursorIcon::Pointer),
            Cursor::Text => self.window.set_cursor(CursorIcon::Text),
            Cursor::Wait => self.window.set_cursor(CursorIcon::Wait),
            Cursor::Help => self.window.set_cursor(CursorIcon::Help),
            Cursor::Progress => self.window.set_cursor(CursorIcon::Progress),
            Cursor::NotAllowed => self.window.set_cursor(CursorIcon::NotAllowed),
            Cursor::ContextMenu => self.window.set_cursor(CursorIcon::ContextMenu),
            Cursor::Cell => self.window.set_cursor(CursorIcon::Cell),
            Cursor::Crosshair => self.window.set_cursor(CursorIcon::Crosshair),
            Cursor::VerticalText => self.window.set_cursor(CursorIcon::VerticalText),
            Cursor::Alias => self.window.set_cursor(CursorIcon::Alias),
            Cursor::Copy => self.window.set_cursor(CursorIcon::Copy),
            Cursor::NoDrop => self.window.set_cursor(CursorIcon::NoDrop),
            Cursor::Grab => self.window.set_cursor(CursorIcon::Grab),
            Cursor::Grabbing => self.window.set_cursor(CursorIcon::Grabbing),
            Cursor::AllScroll => self.window.set_cursor(CursorIcon::AllScroll),
            Cursor::ColResize => self.window.set_cursor(CursorIcon::ColResize),
            Cursor::RowResize => self.window.set_cursor(CursorIcon::RowResize),
            Cursor::NResize => self.window.set_cursor(CursorIcon::NResize),
            Cursor::EResize => self.window.set_cursor(CursorIcon::EResize),
            Cursor::SResize => self.window.set_cursor(CursorIcon::SResize),
            Cursor::WResize => self.window.set_cursor(CursorIcon::WResize),
            Cursor::NeResize => self.window.set_cursor(CursorIcon::NeResize),
            Cursor::NwResize => self.window.set_cursor(CursorIcon::NwResize),
            Cursor::SeResize => self.window.set_cursor(CursorIcon::SeResize),
            Cursor::SwResize => self.window.set_cursor(CursorIcon::SwResize),
            Cursor::EwResize => self.window.set_cursor(CursorIcon::EwResize),
            Cursor::NsResize => self.window.set_cursor(CursorIcon::NsResize),
            Cursor::NeswResize => self.window.set_cursor(CursorIcon::NeswResize),
            Cursor::NwseResize => self.window.set_cursor(CursorIcon::NwseResize),
            _ => self.window.set_cursor(CursorIcon::Default),
        }
    }

    fn notify_focus_changed(&self, _webview: WebView, focused: bool) {
        println!("[pw_servo] Servo notified focus changed: {}", focused);
    }

    fn show_embedder_control(&self, _webview: WebView, control: EmbedderControl) {
        match control {
            EmbedderControl::ContextMenu(menu) => {
                #[cfg(target_os = "macos")]
                {
                    if let Some(mtm) = MainThreadMarker::new() {
                        self.show_native_context_menu(mtm, menu);
                        return;
                    }
                }
                menu.dismiss();
            }
            _ => {
                println!("[pw_servo] Unhandled embedder control: {:?}", control.id());
            }
        }
    }

    fn notify_input_event_handled(
        &self,
        _webview: WebView,
        _id: InputEventId,
        result: InputEventResult,
    ) {
        // Here we could handle events that Servo didn't consume.
        // For Tab keys, Servo often doesn't consume them if it's not moving between internal elements.
        if !result.intersects(InputEventResult::Consumed | InputEventResult::DefaultPrevented) {
            // println!("[pw_servo] Event was not consumed by Servo");
        }
    }
}

struct AppState {
    servo: Option<Servo>,
    webview: Option<WebView>,
    window: Option<Arc<Window>>,
    window_rendering_context: Option<Rc<WindowRenderingContext>>,
    offscreen_rendering_context: Option<Rc<OffscreenRenderingContext>>,
    needs_repaint: Rc<Cell<bool>>,
    proxy: EventLoopProxy<UserEvent>,
    initial_url: String,
    initial_title: String,
    initial_size: (u32, i32),
    last_mouse_position: Cell<Point2D<f32, DevicePixel>>,
    modifiers_state: Cell<winit::keyboard::ModifiersState>,
    pressed_mouse_buttons: Cell<u16>,
}

impl AppState {
    /// Drive servo forward and repaint if needed.
    /// This mirrors servoshell's pattern: spin events, then repaint.
    fn pump_servo(&mut self) {
        if let Some(servo) = &self.servo {
            servo.spin_event_loop();
        }

        // After spinning, check if we need to repaint
        if self.needs_repaint.take() {
            self.repaint();
        }
    }

    fn repaint(&self) {
        if let (Some(webview), Some(window_rc), Some(offscreen_rc), Some(window)) = (
            &self.webview,
            &self.window_rendering_context,
            &self.offscreen_rendering_context,
            &self.window,
        ) {
            // 1. Make offscreen context current (ensure Servo renders to FBO)
            offscreen_rc
                .make_current()
                .expect("Failed to make offscreen context current");
            offscreen_rc.prepare_for_rendering();

            // 2. Servo paints to FBO
            webview.paint();

            // 3. Blit Servo output
            window_rc
                .make_current()
                .expect("Failed to make window context current");
            window_rc.prepare_for_rendering(); // Bind window FBO

            let gl = window_rc.glow_gl_api();

            if let Some(cb) = offscreen_rc.render_to_parent_callback() {
                let size = window.inner_size();
                let rect = Rect::new(
                    Point2D::origin(),
                    Size2D::new(size.width as i32, size.height as i32),
                );
                cb(&gl, rect);
            }

            // 4. Present
            window_rc.present();
        }
    }
}

#[cfg(target_os = "macos")]
fn force_srgb_color_space(window_handle: raw_window_handle::RawWindowHandle) {
    if let raw_window_handle::RawWindowHandle::AppKit(handle) = window_handle {
        // Safety: We are on main thread (winit event loop)
        unsafe {
            if let Some(_mtm) = MainThreadMarker::new() {
                let view_ptr = handle.ns_view.as_ptr() as *mut NSView;
                if !view_ptr.is_null() {
                    let view = &*view_ptr;
                    if let Some(window) = view.window() {
                        window.setColorSpace(Some(&NSColorSpace::sRGBColorSpace()));
                    }
                }
            }
        }
    }
}

#[cfg(not(target_os = "macos"))]
fn force_srgb_color_space(_window_handle: raw_window_handle::RawWindowHandle) {
    // No-op
}

impl ApplicationHandler<UserEvent> for AppState {
    fn resumed(&mut self, event_loop: &ActiveEventLoop) {
        if self.window.is_some() {
            return;
        }

        println!("[pw_servo] App resumed, creating window...");
        let window_attributes = WindowAttributes::default()
            .with_title(&self.initial_title)
            .with_inner_size(winit::dpi::LogicalSize::new(
                self.initial_size.0 as f64,
                self.initial_size.1 as f64,
            ))
            .with_visible(true);

        let window = Arc::new(
            event_loop
                .create_window(window_attributes)
                .expect("Failed to create window"),
        );
        self.window = Some(window.clone());

        let window_handle = window.window_handle().expect("Failed to get window handle");
        force_srgb_color_space(window_handle.as_raw());

        println!(
            "[pw_servo] Window created. Physical size: {:?}, Scale factor: {}",
            window.inner_size(),
            window.scale_factor()
        );

        println!("[pw_servo] Creating WindowRenderingContext...");
        let display_handle = event_loop
            .display_handle()
            .expect("Failed to get display handle");

        let window_rc = Rc::new(
            WindowRenderingContext::new(display_handle, window_handle, window.inner_size())
                .expect("Failed to create WindowRenderingContext"),
        );
        window_rc
            .make_current()
            .expect("Failed to make window context current");

        println!("[pw_servo] Creating OffscreenRenderingContext...");
        let offscreen_rc = Rc::new(window_rc.offscreen_context(window.inner_size()));

        self.window_rendering_context = Some(window_rc.clone());
        self.offscreen_rendering_context = Some(offscreen_rc.clone());

        println!("[pw_servo] Creating Servo instance...");
        let waker = Box::new(JsonWaker {
            proxy: self.proxy.clone(),
        });

        let servo = ServoBuilder::default().event_loop_waker(waker).build();

        servo.setup_logging();

        println!("[pw_servo] Creating WebView for: {}", self.initial_url);
        let url =
            Url::parse(&self.initial_url).unwrap_or_else(|_| Url::parse("about:blank").unwrap());

        let delegate = Rc::new(PyWireWebViewDelegate {
            window: window.clone(),
            needs_repaint: self.needs_repaint.clone(),
        });

        // Pass the offscreen context to the WebView
        let webview = WebViewBuilder::new(&servo, offscreen_rc.clone())
            .delegate(delegate)
            .url(url)
            .hidpi_scale_factor(Scale::new(window.scale_factor() as f32))
            .build();

        self.servo = Some(servo);
        self.webview = Some(webview.clone());

        webview.show();
        webview.focus();
        window.focus_window();

        // Kick off the first spin to start loading
        self.pump_servo();

        window.request_redraw();
        event_loop.set_control_flow(ControlFlow::Wait);
    }

    fn window_event(&mut self, event_loop: &ActiveEventLoop, _id: WindowId, event: WindowEvent) {
        match event {
            WindowEvent::CloseRequested => {
                println!("[pw_servo] Close requested, exiting...");
                event_loop.exit();
                return;
            }
            WindowEvent::Focused(focused) => {
                println!("[pw_servo] Window focused: {}", focused);
                if let Some(webview) = &self.webview {
                    if focused {
                        webview.focus();
                    } else {
                        webview.blur();
                        println!("[pw_servo] Window lost focus, blurring webview");
                    }
                }
            }
            WindowEvent::Resized(size) => {
                println!("[pw_servo] Resized to {:?}", size);
                // Resize both contexts
                if let Some(rc) = &self.window_rendering_context {
                    rc.resize(size);
                }
                // Offscreen context resize logic might need to check if webview resizes internally?
                // Actually webview.resize will call resize on its context (offscreen_rc)
                if let Some(webview) = &self.webview {
                    webview.resize(size);
                }
            }
            WindowEvent::ScaleFactorChanged {
                scale_factor,
                inner_size_writer: _,
            } => {
                println!("[pw_servo] Scale factor changed to {}", scale_factor);
                if let Some(webview) = &self.webview {
                    webview.set_hidpi_scale_factor(Scale::new(scale_factor as f32));
                }
            }
            WindowEvent::CursorLeft { .. } => {
                if let Some(webview) = &self.webview {
                    webview.notify_input_event(InputEvent::MouseLeftViewport(Default::default()));
                }
            }
            WindowEvent::CursorMoved { position, .. } => {
                let point = Point2D::new(position.x as f32, position.y as f32);
                self.last_mouse_position.set(point);
                if let Some(webview) = &self.webview {
                    let servo_point = DevicePoint::new(point.x, point.y);
                    let buttons = self.pressed_mouse_buttons.get();
                    if buttons != 0 {
                        println!(
                            "[pw_servo] MouseMove at {:?} with buttons={}",
                            point, buttons
                        );
                    }
                    webview.notify_input_event(InputEvent::MouseMove(
                        MouseMoveEvent::new_with_buttons(servo_point.into(), buttons),
                    ));
                }
            }
            WindowEvent::MouseInput { state, button, .. } => {
                let action = match state {
                    ElementState::Pressed => MouseButtonAction::Down,
                    ElementState::Released => MouseButtonAction::Up,
                };
                let servo_button = match button {
                    MouseButton::Left => ServoMouseButton::Left,
                    MouseButton::Right => ServoMouseButton::Right,
                    MouseButton::Middle => ServoMouseButton::Middle,
                    MouseButton::Back => ServoMouseButton::Back,
                    MouseButton::Forward => ServoMouseButton::Forward,
                    MouseButton::Other(v) => ServoMouseButton::Other(v),
                };

                let button_mask = match servo_button {
                    ServoMouseButton::Left => 1,
                    ServoMouseButton::Right => 2,
                    ServoMouseButton::Middle => 4,
                    ServoMouseButton::Back => 8,
                    ServoMouseButton::Forward => 16,
                    _ => 0,
                };
                let mut current_buttons = self.pressed_mouse_buttons.get();
                if action == MouseButtonAction::Down {
                    current_buttons |= button_mask;
                } else {
                    current_buttons &= !button_mask;
                }
                self.pressed_mouse_buttons.set(current_buttons);

                println!(
                    "[pw_servo] MouseInput {:?} button={:?} mask={} total_buttons={}",
                    action, servo_button, button_mask, current_buttons
                );

                let point = self.last_mouse_position.get();
                if let Some(webview) = &self.webview {
                    let servo_point = DevicePoint::new(point.x, point.y);
                    webview.notify_input_event(InputEvent::MouseButton(MouseButtonEvent::new(
                        action,
                        servo_button,
                        servo_point.into(),
                    )));
                }
            }
            WindowEvent::ModifiersChanged(modifiers) => {
                self.modifiers_state.set(modifiers.state());
            }
            WindowEvent::KeyboardInput { event, .. } => {
                if let Some(webview) = &self.webview {
                    let servo_event = keyboard_event_from_winit(&event, self.modifiers_state.get());
                    let mut handled = false;

                    // Intercept clipboard shortcuts (Cmd+C/X/V)
                    if servo_event.event.state == servo::KeyState::Down {
                        let mods = servo_event.event.modifiers;
                        let cmd_or_ctrl = mods.contains(servo::Modifiers::CONTROL)
                            || mods.contains(servo::Modifiers::META);

                        if cmd_or_ctrl {
                            match servo_event.event.key {
                                servo::Key::Character(ref c) if c == "c" || c == "C" => {
                                    webview.notify_input_event(InputEvent::EditingAction(
                                        EditingActionEvent::Copy,
                                    ));
                                    handled = true;
                                }
                                servo::Key::Character(ref c) if c == "x" || c == "X" => {
                                    webview.notify_input_event(InputEvent::EditingAction(
                                        EditingActionEvent::Cut,
                                    ));
                                    handled = true;
                                }
                                servo::Key::Character(ref c) if c == "v" || c == "V" => {
                                    webview.notify_input_event(InputEvent::EditingAction(
                                        EditingActionEvent::Paste,
                                    ));
                                    handled = true;
                                }
                                _ => {}
                            }
                        }
                    }

                    if !handled {
                        webview.notify_input_event(InputEvent::Keyboard(servo_event));
                    }
                }
            }
            WindowEvent::MouseWheel { delta, .. } => {
                println!("[pw_servo] MouseWheel: {:?}", delta);
                const LINE_HEIGHT: f32 = 76.0;
                const LINE_WIDTH: f32 = 76.0;

                let (delta_x, delta_y, mode) = match delta {
                    MouseScrollDelta::LineDelta(x, y) => {
                        (x * LINE_WIDTH, y * LINE_HEIGHT, WheelMode::DeltaPixel)
                    }
                    MouseScrollDelta::PixelDelta(pos) => {
                        (pos.x as f32, pos.y as f32, WheelMode::DeltaPixel)
                    }
                };

                let point = self.last_mouse_position.get();
                if let Some(webview) = &self.webview {
                    webview.notify_input_event(InputEvent::Wheel(WheelEvent::new(
                        WheelDelta {
                            x: delta_x as f64,
                            y: delta_y as f64,
                            z: 0.0,
                            mode,
                        },
                        DevicePoint::new(point.x, point.y).into(),
                    )));
                }
            }
            WindowEvent::RedrawRequested => {
                println!("[pw_servo] RedrawRequested");
                self.repaint();
            }
            _ => (),
        }

        // Critical: pump Servo on EVERY window event, just like servoshell does.
        self.pump_servo();
    }

    fn user_event(&mut self, _event_loop: &ActiveEventLoop, event: UserEvent) {
        match event {
            UserEvent::Wake => {
                self.pump_servo();
            }
            UserEvent::ExecuteJs(script) => {
                if let Some(webview) = &self.webview {
                    webview.evaluate_javascript(script, |_result| {
                        // For now we don't handle the result back to Python
                    });
                }
            }
            UserEvent::SetTitle(title) => {
                if let Some(window) = &self.window {
                    window.set_title(&title);
                }
            }
            UserEvent::Resize(width, height) => {
                if let Some(window) = &self.window {
                    let _ = window.request_inner_size(winit::dpi::LogicalSize::new(
                        width as f64,
                        height as f64,
                    ));
                }
            }
        }
    }
}

#[no_mangle]
#[allow(clippy::not_unsafe_ptr_arg_deref)]
pub extern "C" fn pw_execute_javascript(script: *const c_char) -> i32 {
    let script = unsafe {
        if script.is_null() {
            return -1;
        }
        CStr::from_ptr(script).to_string_lossy().into_owned()
    };

    if let Some(proxy) = PROXY.get() {
        if proxy.send_event(UserEvent::ExecuteJs(script)).is_ok() {
            0
        } else {
            -2
        }
    } else {
        -3
    }
}

#[no_mangle]
#[allow(clippy::not_unsafe_ptr_arg_deref)]
pub extern "C" fn pw_set_title(title: *const c_char) -> i32 {
    let title = unsafe {
        if title.is_null() {
            return -1;
        }
        CStr::from_ptr(title).to_string_lossy().into_owned()
    };

    if let Some(proxy) = PROXY.get() {
        if proxy.send_event(UserEvent::SetTitle(title)).is_ok() {
            0
        } else {
            -2
        }
    } else {
        -3
    }
}

#[no_mangle]
pub extern "C" fn pw_resize_window(width: u32, height: u32) -> i32 {
    if let Some(proxy) = PROXY.get() {
        if proxy.send_event(UserEvent::Resize(width, height)).is_ok() {
            0
        } else {
            -2
        }
    } else {
        -3
    }
}

#[no_mangle]
pub extern "C" fn pw_version() -> *const c_char {
    c"0.2.0".as_ptr()
}

#[no_mangle]
#[allow(clippy::not_unsafe_ptr_arg_deref)]
pub extern "C" fn pw_start_app(params: InitParams) -> i32 {
    let res = std::panic::catch_unwind(|| {
        let title = unsafe {
            if params.title.is_null() {
                "PyWire Shell".to_string()
            } else {
                CStr::from_ptr(params.title)
                    .to_str()
                    .unwrap_or("PyWire Shell")
                    .to_string()
            }
        };

        let url = unsafe {
            if params.url.is_null() {
                "about:blank".to_string()
            } else {
                CStr::from_ptr(params.url)
                    .to_str()
                    .unwrap_or("about:blank")
                    .to_string()
            }
        };

        // Initialize Servo resources
        let resources_path = env::var("SERVO_RESOURCES_PATH")
            .map(PathBuf::from)
            .expect("SERVO_RESOURCES_PATH must be set");

        if !resources_path.exists() {
            panic!("SERVO_RESOURCES_PATH does not exist: {:?}", resources_path);
        }

        resources::set(Box::new(PyWireResourceReader {
            path: resources_path,
        }));

        // Initialize crypto
        match rustls::crypto::aws_lc_rs::default_provider().install_default() {
            Ok(_) => (),
            Err(_) => println!("[pw_servo] Warning: crypto provider already installed"),
        }

        let event_loop = EventLoop::with_user_event().build().unwrap();
        let proxy = event_loop.create_proxy();
        let _ = PROXY.set(proxy.clone());

        unsafe {
            ON_EVENT_CALLBACK = params.on_event;
        }

        let mut app = AppState {
            servo: None,
            webview: None,
            window: None,
            window_rendering_context: None,
            offscreen_rendering_context: None,
            needs_repaint: Rc::new(Cell::new(false)),
            proxy,
            initial_url: url,
            initial_title: title,
            initial_size: (params.width, params.height),
            last_mouse_position: Cell::new(Point2D::origin()),
            modifiers_state: Cell::new(Default::default()),
            pressed_mouse_buttons: Cell::new(0),
        };

        // println!("[pw_servo] Entering event loop...");
        event_loop.run_app(&mut app).unwrap();
    });

    match res {
        Ok(_) => 0,
        Err(_) => -1,
    }
}
