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

/// <summary>
/// WP1-4: ParameterType → 可見性轉換器——用於在 Property Manager 中根據參數型別顯示對應控件。
/// </summary>
public static class EnumEqualsConverter
{
    public static readonly IsNumberConverter IsNumber = new();
    public static readonly IsDropdownConverter IsDropdown = new();
    public static readonly IsCheckboxConverter IsCheckbox = new();
    public static readonly IsReferenceConverter IsReference = new();
    public static readonly IsReadOnlyConverter IsReadOnly = new();
}

public class IsNumberConverter : IValueConverter
{
    public object Convert(object? value, Type targetType, object? parameter, CultureInfo culture) =>
        value is ParameterType pt && pt == ParameterType.Number;
    public object ConvertBack(object? value, Type targetType, object? parameter, CultureInfo culture) =>
        throw new NotSupportedException();
}

public class IsDropdownConverter : IValueConverter
{
    public object Convert(object? value, Type targetType, object? parameter, CultureInfo culture) =>
        value is ParameterType pt && pt == ParameterType.Dropdown;
    public object ConvertBack(object? value, Type targetType, object? parameter, CultureInfo culture) =>
        throw new NotSupportedException();
}

public class IsCheckboxConverter : IValueConverter
{
    public object Convert(object? value, Type targetType, object? parameter, CultureInfo culture) =>
        value is ParameterType pt && pt == ParameterType.Checkbox;
    public object ConvertBack(object? value, Type targetType, object? parameter, CultureInfo culture) =>
        throw new NotSupportedException();
}

public class IsReferenceConverter : IValueConverter
{
    public object Convert(object? value, Type targetType, object? parameter, CultureInfo culture) =>
        value is ParameterType pt && pt == ParameterType.Reference;
    public object ConvertBack(object? value, Type targetType, object? parameter, CultureInfo culture) =>
        throw new NotSupportedException();
}

public class IsReadOnlyConverter : IValueConverter
{
    public object Convert(object? value, Type targetType, object? parameter, CultureInfo culture) =>
        value is ParameterType pt && pt == ParameterType.ReadOnly;
    public object ConvertBack(object? value, Type targetType, object? parameter, CultureInfo culture) =>
        throw new NotSupportedException();
}

/// <summary>
/// WP1-4: 字串 ↔ 布林轉換器——用於 Checkbox 參數型別。
/// </summary>
public class StringToBoolConverter : IValueConverter
{
    public static readonly StringToBoolConverter Instance = new();
    public object Convert(object? value, Type targetType, object? parameter, CultureInfo culture) =>
        value is string s && (s.Equals("true", StringComparison.OrdinalIgnoreCase) || s == "1" || s == "yes");
    public object ConvertBack(object? value, Type targetType, object? parameter, CultureInfo culture) =>
        value is bool b ? (b ? "true" : "false") : "false";
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