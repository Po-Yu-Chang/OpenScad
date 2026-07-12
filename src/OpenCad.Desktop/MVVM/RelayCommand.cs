using System.Windows.Input;

namespace OpenCad.MVVM;

/// <summary>
/// 簡易 RelayCommand 實作。
/// </summary>
public class RelayCommand : ICommand
{
    private readonly Action _execute;
    private readonly Func<bool>? _canExecute;
    private readonly Action<Exception>? _onError;

    public RelayCommand(Action execute, Func<bool>? canExecute = null, Action<Exception>? onError = null)
    {
        _execute = execute;
        _canExecute = canExecute;
        _onError = onError;
    }

    public bool CanExecute(object? parameter) => _canExecute?.Invoke() ?? true;

    public void Execute(object? parameter)
    {
        try { _execute(); }
        catch (Exception ex)
        {
            if (_onError == null) throw;   // 無處理器時不吞例外——讓上層可見
            _onError(ex);
        }
    }

    public event EventHandler? CanExecuteChanged;

    /// <summary>
    /// 通知 CanExecute 狀態已變更，觸發 CanExecuteChanged 事件以更新 UI 按鈕啟用／停用狀態。
    /// </summary>
    public void RaiseCanExecuteChanged() =>
        CanExecuteChanged?.Invoke(this, EventArgs.Empty);
}

public class RelayCommand<T> : ICommand
{
    private readonly Action<T?> _execute;
    private readonly Func<T?, bool>? _canExecute;
    private readonly Action<Exception>? _onError;

    public RelayCommand(Action<T?> execute, Func<T?, bool>? canExecute = null, Action<Exception>? onError = null)
    {
        _execute = execute;
        _canExecute = canExecute;
        _onError = onError;
    }

    // parameter 為 null 時不硬轉型（enum/值型別會擲例外），改用模式比對安全取值
    public bool CanExecute(object? parameter) => _canExecute?.Invoke(parameter is T t ? t : default) ?? true;

    public void Execute(object? parameter)
    {
        try { _execute(parameter is T t ? t : default); }
        catch (Exception ex)
        {
            if (_onError == null) throw;
            _onError(ex);
        }
    }

    public event EventHandler? CanExecuteChanged;

    /// <summary>
    /// 通知 CanExecute 狀態已變更，觸發 CanExecuteChanged 事件以更新 UI 按鈕啟用／停用狀態。
    /// </summary>
    public void RaiseCanExecuteChanged() =>
        CanExecuteChanged?.Invoke(this, EventArgs.Empty);
}