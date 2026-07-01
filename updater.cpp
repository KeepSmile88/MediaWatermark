#if defined(_MSC_VER)
#pragma execution_character_set("utf-8")
#endif

#include <windows.h>
#include <tlhelp32.h>
#include <string>
#include <iostream>
#include <fstream>
#include <chrono>

using namespace std;

// 记录日志，保持和之前 Python 一致的行为
void LogInfo(const string& logFile, const string& message) {
    ofstream file;
    file.open(logFile, ios_base::app);
    if (file.is_open()) {
        auto now = chrono::system_clock::now();
        time_t t = chrono::system_clock::to_time_t(now);
        char buf[100];
        ctime_s(buf, sizeof(buf), &t);
        string timeStr(buf);
        timeStr.pop_back(); // Remove newline
        file << timeStr << " :\tINFO\t" << message << endl;
        file.close();
    }
}

// 强制结束主进程 
void KillProcessByName(const wstring& processName, const string& logFile) {
    HANDLE hSnapShot = CreateToolhelp32Snapshot(TH32CS_SNAPALL, NULL);
    PROCESSENTRY32W pEntry;
    pEntry.dwSize = sizeof(pEntry);
    BOOL hRes = Process32FirstW(hSnapShot, &pEntry);
    while (hRes) {
        if (wcscmp(pEntry.szExeFile, processName.c_str()) == 0) {
            HANDLE hProcess = OpenProcess(PROCESS_TERMINATE, 0, (DWORD)pEntry.th32ProcessID);
            if (hProcess != NULL) {
                TerminateProcess(hProcess, 9);
                CloseHandle(hProcess);
                LogInfo(logFile, string("成功强制终止原进程: ") + string(processName.begin(), processName.end()));
            }
        }
        hRes = Process32NextW(hSnapShot, &pEntry);
    }
    CloseHandle(hSnapShot);
}

// 执行 DOS 目录覆盖/拷贝命令 (最稳且原生的方案)
bool ExecuteCopyCmd(const wstring& source, const wstring& dest, const string& logFile) {
    wstring cmd = L"cmd.exe /c xcopy /Y /E /H /I /C \"" + source + L"\\*\" \"" + dest + L"\\\"";
    
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    // 隐藏黑框
    si.dwFlags = STARTF_USESHOWWINDOW;
    si.wShowWindow = SW_HIDE;
    ZeroMemory(&pi, sizeof(pi));

    if (CreateProcessW(NULL, &cmd[0], NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, NULL, &si, &pi)) {
        WaitForSingleObject(pi.hProcess, INFINITE);
        CloseHandle(pi.hProcess);
        CloseHandle(pi.hThread);
        return true;
    }
    LogInfo(logFile, "执行拷贝命令失败");
    return false;
}

// 启动新进程
void StartApplication(const wstring& exePath, const wstring& workingDir, const string& logFile) {
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    ZeroMemory(&pi, sizeof(pi));

    if (CreateProcessW(exePath.c_str(), NULL, NULL, NULL, FALSE, 0, NULL, workingDir.c_str(), &si, &pi)) {
        LogInfo(logFile, "已成功重启主程序");
        CloseHandle(pi.hProcess);
        CloseHandle(pi.hThread);
    } else {
        LogInfo(logFile, "重启主程序时发生错误！");
    }
}

// 工具函数：wstring 转 string (UTF-8) 用于日志
string ws2s(const wstring& wstr) {
    if (wstr.empty()) return string();
    int size_needed = WideCharToMultiByte(CP_UTF8, 0, &wstr[0], (int)wstr.size(), NULL, 0, NULL, NULL);
    string strTo(size_needed, 0);
    WideCharToMultiByte(CP_UTF8, 0, &wstr[0], (int)wstr.size(), &strTo[0], size_needed, NULL, NULL);
    return strTo;
}


int APIENTRY wWinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance, LPWSTR lpCmdLine, int nCmdShow) {
    
    // 初始化日志路径 (AppData/Roaming/多媒体水印助手/logs/app.log)
    char appDataPath[MAX_PATH];
    ExpandEnvironmentStringsA("%APPDATA%", appDataPath, MAX_PATH);
    // 修复转义符和中文字符串末尾可能被 MSVC 错误吞掉的斜杠
    string logFolder = string(appDataPath) + "\\多媒体水印助手\\logs";
    string logFile = logFolder + "\\app.log";
    // 确保日志目录存在
    CreateDirectoryA(logFolder.c_str(), NULL);
    
    LogInfo(logFile, "================ Pure C++ 原生更新器启动 ================");

    // 解析命令行参数
    int argc;
    LPWSTR* argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    if (argc < 5) {
        LogInfo(logFile, "参数不足！用法: update.exe <install_path> <new_version_path> <backup_path> <main_exe_name> ");
        return 1;
    }

    wstring installPath = argv[1];
    wstring newVersionPath = argv[2];
    wstring backupPath = argv[3];
    wstring mainExeName = argv[4];

    LogInfo(logFile, "安装路径:  " + ws2s(installPath));
    LogInfo(logFile, "新版路径:  " + ws2s(newVersionPath));

    // 1. 等待主程序自然退出
    Sleep(2000);

    // 2. 强制终止残留的主进程 (保险起见)
    KillProcessByName(mainExeName, logFile);
    Sleep(1000);

    // 3. 备份阶段 
    LogInfo(logFile, "开始备份... ");
    wstring delCmd = L"cmd.exe /c rmdir /s /q \"" + backupPath + L"\"";
    
    // 静默执行清空旧备份命令
    STARTUPINFOW siDel;
    PROCESS_INFORMATION piDel;
    ZeroMemory(&siDel, sizeof(siDel));
    siDel.cb = sizeof(siDel);
    siDel.dwFlags = STARTF_USESHOWWINDOW;
    siDel.wShowWindow = SW_HIDE;
    ZeroMemory(&piDel, sizeof(piDel));

    if (CreateProcessW(NULL, &delCmd[0], NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, NULL, &siDel, &piDel)) {
        WaitForSingleObject(piDel.hProcess, INFINITE);
        CloseHandle(piDel.hProcess);
        CloseHandle(piDel.hThread);
    }
    ExecuteCopyCmd(installPath, backupPath, logFile);

    // 4. 执行替换阶段 
    LogInfo(logFile, "开始覆盖执行热更新... ");
    if (ExecuteCopyCmd(newVersionPath, installPath, logFile)) {
        LogInfo(logFile, "文件覆盖完成！ ");
    }

    // 5. 组装新程序的完整路径并启动
    wstring fullExePath = installPath + L"\\" + mainExeName;
    StartApplication(fullExePath, installPath, logFile);

    LogInfo(logFile, "纯 C++ 更新器执行完毕，安全退出。 ");
    
    LocalFree(argv);
    return 0;
}
