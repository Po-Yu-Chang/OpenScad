using System.Windows.Input;

namespace OpenCad.MVVM;

/// <summary>
/// 簡易 RelayCommand 實作。
/// </summary>
public class RelayCommand : ICommand
{
    private readonly Action _execute;
    private readonly Func<bool>? _canExecute;

    public RelayCommand(Action execute, Func<bool>? canExecute = null)
    {
        _execute = execute;
        _canExecute = canExecute;
    }

    public bool CanExecute(object? parameter) => _canExecute?.Invoke() ?? true;
    public void Execute(object? parameter) => _execute();
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

    public RelayCommand(Action<T?> execute, Func<T?, bool>? canExecute = null)
    {
        _execute = execute;
        _canExecute = canExecute;
    }

    public bool CanExecute(object? parameter) => _canExecute?.Invoke((T?)parameter) ?? true;
    public void Execute(object? parameter) => _execute(parameter is T t ? t : default);
    public event EventHandler? CanExecuteChanged;

    /// <summary>
    /// 通知 CanExecute 狀態已變更，觸發 CanExecuteChanged 事件以更新 UI 按鈕啟用／停用狀態。
    /// </summary>
    public void RaiseCanExecuteChanged() =>
        CanExecuteChanged?.Invoke(this, EventArgs.Empty);
}