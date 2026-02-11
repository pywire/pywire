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
use winit::window::{Window, WindowAttributes, WindowId};

#[cfg(target_os = "macos")]
use {
    objc2_app_kit::{NSColorSpace, NSView},
    objc2_foundation::MainThreadMarker,
};

use servo::{
    ConsoleLogLevel, DevicePixel, DevicePoint, EventLoopWaker, InputEvent, LoadStatus,
    MouseButton as ServoMouseButton, MouseButtonAction, MouseButtonEvent, MouseMoveEvent,
    OffscreenRenderingContext, RenderingContext, Servo, ServoBuilder, WebView, WebViewBuilder,
    WebViewDelegate, WheelDelta, WheelEvent, WheelMode, WindowRenderingContext,
    resources::{self, Resource, ResourceReaderMethods},
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

impl WebViewDelegate for PyWireWebViewDelegate {
    fn show_console_message(&self, _webview: WebView, level: ConsoleLogLevel, message: String) {
        // Intercept PW_MSG: prefix for JS -> Python bridge
        if message.starts_with("PW_MSG:") {
            let payload = &message["PW_MSG:".len()..];
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
            WindowEvent::CursorMoved { position, .. } => {
                let point: Point2D<f32, DevicePixel> =
                    Point2D::new(position.x as f32, position.y as f32);
                self.last_mouse_position.set(point.cast_unit());
                if let Some(webview) = &self.webview {
                    webview.notify_input_event(InputEvent::MouseMove(MouseMoveEvent::new(
                        DevicePoint::new(point.x, point.y).into(),
                    )));
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
                let point = self.last_mouse_position.get();
                if let Some(webview) = &self.webview {
                    webview.notify_input_event(InputEvent::MouseButton(MouseButtonEvent::new(
                        action,
                        servo_button,
                        DevicePoint::new(point.x, point.y).into(),
                    )));
                }
            }
            WindowEvent::ModifiersChanged(modifiers) => {
                self.modifiers_state.set(modifiers.state());
            }
            WindowEvent::KeyboardInput { event, .. } => {
                if let Some(webview) = &self.webview {
                    let servo_event = keyboard_event_from_winit(&event, self.modifiers_state.get());
                    webview.notify_input_event(InputEvent::Keyboard(servo_event));
                }
            }
            WindowEvent::MouseWheel { delta, .. } => {
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
                        point.into(),
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
    "0.2.0\0".as_ptr() as *const c_char
}

#[no_mangle]
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
        };

        // println!("[pw_servo] Entering event loop...");
        event_loop.run_app(&mut app).unwrap();
    });

    match res {
        Ok(_) => 0,
        Err(_) => -1,
    }
}
