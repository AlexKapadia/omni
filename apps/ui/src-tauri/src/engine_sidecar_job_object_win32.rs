//! Windows Job Object helpers for the engine sidecar.
//!
//! Places the engine child in a job with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`
//! so force-kill of the shell (Task Manager, crash) also kills the engine tree
//! — honouring the "no orphaned engine" contract.

use std::process::Child;

/// Owned Job Object handle — closing the last handle kills assigned processes.
pub struct WindowsJob {
    handle: isize,
}

impl WindowsJob {
    pub fn handle(&self) -> isize {
        self.handle
    }
}

impl Drop for WindowsJob {
    fn drop(&mut self) {
        // Closing the last job handle with KILL_ON_JOB_CLOSE terminates children.
        unsafe {
            let _ = windows_sys::Win32::Foundation::CloseHandle(self.handle);
        }
    }
}

/// Create a Job Object that kills all assigned processes when the last handle
/// to the job is closed (shell force-kill / crash).
pub fn create_kill_on_close_job() -> Option<WindowsJob> {
    use windows_sys::Win32::Foundation::CloseHandle;
    use windows_sys::Win32::System::JobObjects::{
        CreateJobObjectW, JobObjectExtendedLimitInformation, SetInformationJobObject,
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    };

    unsafe {
        let handle = CreateJobObjectW(std::ptr::null(), std::ptr::null());
        if handle == 0 || handle == -1 {
            log::warn!(target: "engine", "could not create job object for engine sidecar");
            return None;
        }
        let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        let ok = SetInformationJobObject(
            handle,
            JobObjectExtendedLimitInformation,
            &info as *const _ as *const core::ffi::c_void,
            std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
        );
        if ok == 0 {
            log::warn!(target: "engine", "could not set JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE");
            let _ = CloseHandle(handle);
            return None;
        }
        Some(WindowsJob { handle })
    }
}

pub fn assign_child_to_job(job: isize, child: &Child) {
    use std::os::windows::io::AsRawHandle;
    use windows_sys::Win32::System::JobObjects::AssignProcessToJobObject;

    unsafe {
        let process = child.as_raw_handle() as isize;
        if AssignProcessToJobObject(job, process) == 0 {
            log::warn!(
                target: "engine",
                "could not assign engine pid {} to kill-on-close job",
                child.id()
            );
        }
    }
}
