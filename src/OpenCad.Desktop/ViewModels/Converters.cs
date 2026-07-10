using System.Globalization;
using Avalonia.Data.Converters;
using OpenCad.Desktop.ViewModels;

namespace OpenCad.Desktop.ViewModels;

/// <summary>
/// 將 MessageKind 轉為可見性——用於在 ItemsControl 中根據訊息種類顯示對應的 DataTemplate。
/// </summary>
public static class MessageKindToVisibilityConverter
{
    public static readonly UserIsVisibleConverter UserIsVisible = new();
    public static readonly AssistantIsVisibleConverter AssistantIsVisible = new();
    public static readonly ErrorIsVisibleConverter ErrorIsVisible = new();
    public static readonly PlanIsVisibleConverter PlanIsVisible = new();
    public static readonly DiffIsVisibleConverter DiffIsVisible = new();
}

public class UserIsVisibleConverter : IValueConverter
{
    public object Convert(object? value, Type targetType, object? parameter, CultureInfo culture) =>
        value is MessageKind kind && kind == MessageKind.User;
    public object ConvertBack(object? value, Type targetType, object? parameter, CultureInfo culture) =>
        throw new NotSupportedException();
}

public class AssistantIsVisibleConverter : IValueConverter
{
    public object Convert(object? value, Type targetType, object? parameter, CultureInfo culture) =>
        value is MessageKind kind && kind == MessageKind.Assistant;
    public object ConvertBack(object? value, Type targetType, object? parameter, CultureInfo culture) =>
        throw new NotSupportedException();
}

public class ErrorIsVisibleConverter : IValueConverter
{
    public object Convert(object? value, Type targetType, object? parameter, CultureInfo culture) =>
        value is MessageKind kind && kind == MessageKind.Error;
    public object ConvertBack(object? value, Type targetType, object? parameter, CultureInfo culture) =>
        throw new NotSupportedException();
}

public class PlanIsVisibleConverter : IValueConverter
{
    public object Convert(object? value, Type targetType, object? parameter, CultureInfo culture) =>
        value is MessageKind kind && kind == MessageKind.Plan;
    public object ConvertBack(object? value, Type targetType, object? parameter, CultureInfo culture) =>
        throw new NotSupportedException();
}

public class DiffIsVisibleConverter : IValueConverter
{
    public object Convert(object? value, Type targetType, object? parameter, CultureInfo culture) =>
        value is MessageKind kind && kind == MessageKind.Diff;
    public object ConvertBack(object? value, Type targetType, object? parameter, CultureInfo culture) =>
        throw new NotSupportedException();
}