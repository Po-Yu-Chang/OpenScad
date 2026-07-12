using OpenCad.MVVM;

namespace OpenCad.Tests;

/// <summary>
/// RelayCommand / AsyncRelayCommand 錯誤處理與型別安全測試——
/// 對應 2026-07-12「按了沒反應」根治批次：例外不得靜默吞掉、錯型別參數不得擲例外。
/// </summary>
public class RelayCommandErrorTests
{
    [Fact]
    public void RelayCommand_Execute_ExceptionWithOnError_OnErrorReceivesException()
    {
        var exception = new Exception("Test exception");
        Exception? receivedException = null;

        var command = new RelayCommand(
            () => throw exception,
            null,
            ex => receivedException = ex);

        command.Execute(null);

        Assert.Equal(exception, receivedException);
    }

    [Fact]
    public void RelayCommand_Execute_ExceptionWithoutOnError_Rethrows()
    {
        var exception = new Exception("Test exception");
        var command = new RelayCommand(() => throw exception);

        var thrown = Assert.Throws<Exception>(() => command.Execute(null));
        Assert.Equal(exception, thrown);
    }

    [Fact]
    public void RelayCommandT_Execute_ExceptionWithOnError_OnErrorReceivesException()
    {
        var exception = new Exception("Test exception");
        Exception? receivedException = null;

        var command = new RelayCommand<string>(
            _ => throw exception,
            null,
            ex => receivedException = ex);

        command.Execute("test");

        Assert.Equal(exception, receivedException);
    }

    [Fact]
    public void RelayCommandT_Execute_ExceptionWithoutOnError_Rethrows()
    {
        var exception = new Exception("Test exception");
        var command = new RelayCommand<string>(_ => throw exception);

        var thrown = Assert.Throws<Exception>(() => command.Execute("test"));
        Assert.Equal(exception, thrown);
    }

    [Fact]
    public void RelayCommandT_CanExecute_WrongTypeParameter_DoesNotThrow()
    {
        var wasCalled = false;
        var receivedValue = -1;

        var command = new RelayCommand<int>(
            _ => { },
            param =>
            {
                wasCalled = true;
                receivedValue = param;
                return true;
            });

        var result = command.CanExecute("wrong-type-string");

        Assert.True(result);
        Assert.True(wasCalled);
        Assert.Equal(0, receivedValue);   // default(int)
    }

    [Fact]
    public void RelayCommandT_CanExecute_NullParameter_DoesNotThrow()
    {
        var wasCalled = false;
        string? receivedValue = "not null";

        var command = new RelayCommand<string>(
            _ => { },
            param =>
            {
                wasCalled = true;
                receivedValue = param;
                return true;
            });

        var result = command.CanExecute(null);

        Assert.True(result);
        Assert.True(wasCalled);
        Assert.Null(receivedValue);
    }

    [Fact]
    public void RelayCommandT_Execute_NullParameter_PassesDefault()
    {
        string? receivedValue = "not null";
        var command = new RelayCommand<string>(p => receivedValue = p);

        command.Execute(null);

        Assert.Null(receivedValue);
    }

    [Fact]
    public void AsyncRelayCommandT_CanExecute_WrongTypeParameter_DoesNotThrow()
    {
        var wasCalled = false;
        var receivedValue = -1;

        var command = new AsyncRelayCommand<int>(
            _ => Task.CompletedTask,
            param =>
            {
                wasCalled = true;
                receivedValue = param;
                return true;
            });

        var result = command.CanExecute("wrong-type-string");

        Assert.True(result);
        Assert.True(wasCalled);
        Assert.Equal(0, receivedValue);   // default(int)
    }

    [Fact]
    public async Task AsyncRelayCommand_Execute_ExceptionWithOnError_OnErrorReceivesException()
    {
        var exception = new Exception("Test exception");
        Exception? receivedException = null;

        var command = new AsyncRelayCommand(
            () => throw exception,
            null,
            ex => receivedException = ex);

        command.Execute(null);

        // Execute 是 async void——同步擲出的例外在同步段即被 catch，短暫等待保險
        await Task.Delay(10);

        Assert.Equal(exception, receivedException);
    }

    [Fact]
    public async Task AsyncRelayCommand_Execute_WhileRunning_CanExecuteReturnsFalse()
    {
        var tcs = new TaskCompletionSource<bool>();
        var command = new AsyncRelayCommand(() => tcs.Task);

        command.Execute(null);
        await Task.Delay(10);

        Assert.False(command.CanExecute(null));   // _isRunning 再入保護

        tcs.SetResult(true);
        await Task.Delay(10);

        Assert.True(command.CanExecute(null));    // 完成後恢復可執行
    }
}
