param(
  [ValidateSet("server", "primary_snapshot", "root", "focused", "from_point", "active_descendants", "root_descendants", "find", "state", "actions", "click", "set_value", "select", "scroll")]
  [string]$Operation = "find",
  [string]$Query = "",
  [int]$Limit = 40,
  [int]$X = 0,
  [int]$Y = 0,
  [string]$ElementId = "",
  [string]$Text = "",
  [int]$ScrollAmount = -360
)

$ErrorActionPreference = "Stop"
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName WindowsBase

if (-not ("AutoCruiseWin32" -as [type])) {
  Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class AutoCruiseWin32 {
  [DllImport("user32.dll")]
  public static extern IntPtr GetForegroundWindow();
}
"@
}

if (-not ("AutoCruiseEventBridge" -as [type])) {
  Add-Type -ReferencedAssemblies UIAutomationClient,UIAutomationTypes,WindowsBase @"
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Windows.Automation;

public sealed class AutoCruiseEventRecord {
  public string type { get; set; }
  public string runtime_id { get; set; }
  public string name { get; set; }
  public string detail { get; set; }
  public int process_id { get; set; }
  public string timestamp { get; set; }
}

public static class AutoCruiseEventBridge {
  private static readonly ConcurrentQueue<AutoCruiseEventRecord> Queue = new ConcurrentQueue<AutoCruiseEventRecord>();

  public static void Enqueue(string type, AutomationElement element, string detail) {
    string runtimeId = "";
    string name = "";
    int processId = 0;
    if (element != null) {
      try {
        var raw = element.GetRuntimeId();
        if (raw != null && raw.Length > 0) {
          runtimeId = string.Join(".", raw);
        }
      } catch {}
      try { name = element.Current.Name ?? ""; } catch {}
      try { processId = element.Current.ProcessId; } catch {}
    }
    Queue.Enqueue(new AutoCruiseEventRecord {
      type = type ?? "",
      runtime_id = runtimeId,
      name = name,
      detail = detail ?? "",
      process_id = processId,
      timestamp = DateTime.UtcNow.ToString("o")
    });
  }

  public static AutoCruiseEventRecord[] Drain() {
    var items = new List<AutoCruiseEventRecord>();
    AutoCruiseEventRecord item;
    while (Queue.TryDequeue(out item)) {
      items.Add(item);
    }
    return items.ToArray();
  }

  public static void HandleFocusChanged(object sender, AutomationFocusChangedEventArgs e) {
    AutoCruiseEventBridge.Enqueue("focus_changed", sender as AutomationElement, "focus");
  }

  public static void HandlePropertyChanged(object sender, AutomationPropertyChangedEventArgs e) {
    var detail = e.Property != null ? e.Property.ProgrammaticName : "";
    AutoCruiseEventBridge.Enqueue("property_changed", sender as AutomationElement, detail);
  }

  public static void HandleStructureChanged(object sender, StructureChangedEventArgs e) {
    AutoCruiseEventBridge.Enqueue("structure_changed", sender as AutomationElement, e.StructureChangeType.ToString());
  }
}
"@
}

$PatternSpecs = @(
  @{ Name = "Invoke"; Pattern = [System.Windows.Automation.InvokePattern]::Pattern; Available = [System.Windows.Automation.AutomationElement]::IsInvokePatternAvailableProperty },
  @{ Name = "Value"; Pattern = [System.Windows.Automation.ValuePattern]::Pattern; Available = [System.Windows.Automation.AutomationElement]::IsValuePatternAvailableProperty },
  @{ Name = "SelectionItem"; Pattern = [System.Windows.Automation.SelectionItemPattern]::Pattern; Available = [System.Windows.Automation.AutomationElement]::IsSelectionItemPatternAvailableProperty },
  @{ Name = "ExpandCollapse"; Pattern = [System.Windows.Automation.ExpandCollapsePattern]::Pattern; Available = [System.Windows.Automation.AutomationElement]::IsExpandCollapsePatternAvailableProperty },
  @{ Name = "Toggle"; Pattern = [System.Windows.Automation.TogglePattern]::Pattern; Available = [System.Windows.Automation.AutomationElement]::IsTogglePatternAvailableProperty },
  @{ Name = "Scroll"; Pattern = [System.Windows.Automation.ScrollPattern]::Pattern; Available = [System.Windows.Automation.AutomationElement]::IsScrollPatternAvailableProperty },
  @{ Name = "Text"; Pattern = [System.Windows.Automation.TextPattern]::Pattern; Available = [System.Windows.Automation.AutomationElement]::IsTextPatternAvailableProperty },
  @{ Name = "Window"; Pattern = [System.Windows.Automation.WindowPattern]::Pattern; Available = [System.Windows.Automation.AutomationElement]::IsWindowPatternAvailableProperty }
)
$legacyPatternType = [type]::GetType("System.Windows.Automation.LegacyIAccessiblePattern, UIAutomationClient", $false)
$legacyAvailableProperty = [System.Windows.Automation.AutomationElement].GetProperty("IsLegacyIAccessiblePatternAvailableProperty")
if ($null -ne $legacyPatternType -and $null -ne $legacyAvailableProperty) {
  $PatternSpecs += @{
    Name = "LegacyIAccessible"
    Pattern = $legacyPatternType.GetProperty("Pattern").GetValue($null, $null)
    Available = $legacyAvailableProperty.GetValue($null, $null)
  }
}

$script:CacheRequest = $null
$script:FocusHandler = $null
$script:PropertyHandler = $null
$script:StructureHandler = $null
$script:ActivePropertyRoot = $null
$script:ActivePropertyRootId = ""

function New-UiaCacheRequest {
  $cache = [System.Windows.Automation.CacheRequest]::new()
  $cache.AutomationElementMode = [System.Windows.Automation.AutomationElementMode]::Full
  $cache.TreeFilter = [System.Windows.Automation.Automation]::ControlViewCondition
  $cache.TreeScope = [System.Windows.Automation.TreeScope]::Element -bor [System.Windows.Automation.TreeScope]::Children
  foreach ($property in @(
    [System.Windows.Automation.AutomationElement]::NameProperty,
    [System.Windows.Automation.AutomationElement]::AutomationIdProperty,
    [System.Windows.Automation.AutomationElement]::ClassNameProperty,
    [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
    [System.Windows.Automation.AutomationElement]::BoundingRectangleProperty,
    [System.Windows.Automation.AutomationElement]::IsEnabledProperty,
    [System.Windows.Automation.AutomationElement]::HasKeyboardFocusProperty,
    [System.Windows.Automation.AutomationElement]::RuntimeIdProperty,
    [System.Windows.Automation.AutomationElement]::ProcessIdProperty
  )) {
    try { $cache.Add($property) } catch {}
  }
  foreach ($spec in $PatternSpecs) {
    try { $cache.Add($spec.Available) } catch {}
    try { $cache.Add($spec.Pattern) } catch {}
  }
  return $cache
}

function Get-CacheRequest {
  if ($null -eq $script:CacheRequest) {
    $script:CacheRequest = New-UiaCacheRequest
  }
  return $script:CacheRequest
}

function Get-CachedOrCurrent($element, $property, [scriptblock]$fallback) {
  try {
    $cached = $element.GetCachedPropertyValue($property, $true)
    if ($null -ne $cached -and $cached -ne [System.Windows.Automation.AutomationElement]::NotSupported) {
      return $cached
    }
  } catch {}
  try { return & $fallback } catch { return $null }
}

function Get-UiaRuntimeId($element) {
  $value = Get-CachedOrCurrent $element ([System.Windows.Automation.AutomationElement]::RuntimeIdProperty) { $element.GetRuntimeId() }
  if ($value -is [array]) { return @($value | ForEach-Object { [int]$_ }) }
  try { return @($element.GetRuntimeId() | ForEach-Object { [int]$_ }) } catch { return @() }
}

function Get-UiaRuntimeIdString($element) {
  $runtimeId = Get-UiaRuntimeId $element
  if ($runtimeId.Count -eq 0) { return "" }
  return ($runtimeId -join ".")
}

function Get-UiaPatterns($element) {
  $names = [System.Collections.Generic.List[string]]::new()
  foreach ($spec in $PatternSpecs) {
    $available = Get-CachedOrCurrent $element $spec.Available { $element.GetCurrentPropertyValue($spec.Available) }
    if ([bool]$available) {
      [void]$names.Add($spec.Name)
    }
  }
  return $names.ToArray()
}

function Convert-UiaElement($element) {
  if ($null -eq $element) { return $null }
  try {
    $cached = Get-CachedElement $element (Get-CacheRequest)
    $name = Get-CachedOrCurrent $cached ([System.Windows.Automation.AutomationElement]::NameProperty) { $cached.Current.Name }
    $automationId = Get-CachedOrCurrent $cached ([System.Windows.Automation.AutomationElement]::AutomationIdProperty) { $cached.Current.AutomationId }
    $className = Get-CachedOrCurrent $cached ([System.Windows.Automation.AutomationElement]::ClassNameProperty) { $cached.Current.ClassName }
    $controlType = Get-CachedOrCurrent $cached ([System.Windows.Automation.AutomationElement]::ControlTypeProperty) { $cached.Current.ControlType }
    $rect = Get-CachedOrCurrent $cached ([System.Windows.Automation.AutomationElement]::BoundingRectangleProperty) { $cached.Current.BoundingRectangle }
    $isEnabled = Get-CachedOrCurrent $cached ([System.Windows.Automation.AutomationElement]::IsEnabledProperty) { $cached.Current.IsEnabled }
    $hasFocus = Get-CachedOrCurrent $cached ([System.Windows.Automation.AutomationElement]::HasKeyboardFocusProperty) { $cached.Current.HasKeyboardFocus }
    $processId = Get-CachedOrCurrent $cached ([System.Windows.Automation.AutomationElement]::ProcessIdProperty) { $cached.Current.ProcessId }
    $runtimeId = Get-UiaRuntimeId $cached
    return [pscustomobject]@{
      element_id = ($runtimeId -join ".")
      name = [string]$name
      automation_id = [string]$automationId
      class_name = [string]$className
      control_type = if ($null -ne $controlType) { [string]$controlType.ProgrammaticName } else { "" }
      bounding_rectangle = [pscustomobject]@{
        left = [int][Math]::Round($rect.Left)
        top = [int][Math]::Round($rect.Top)
        width = [int][Math]::Round($rect.Width)
        height = [int][Math]::Round($rect.Height)
      }
      left = [int][Math]::Round($rect.Left)
      top = [int][Math]::Round($rect.Top)
      width = [int][Math]::Round($rect.Width)
      height = [int][Math]::Round($rect.Height)
      is_enabled = [bool]$isEnabled
      has_keyboard_focus = [bool]$hasFocus
      runtime_id = $runtimeId
      process_id = [int]$processId
      patterns = @(Get-UiaPatterns $cached)
    }
  } catch {
    return $null
  }
}

function Get-ActiveWindowElement {
  try {
    $handle = [AutoCruiseWin32]::GetForegroundWindow()
    if ($handle -ne [IntPtr]::Zero) {
      return [System.Windows.Automation.AutomationElement]::FromHandle($handle)
    }
  } catch {}
  return $null
}

function Get-RootForScope($scope) {
  if ($scope -eq "active") {
    $active = Get-ActiveWindowElement
    if ($null -ne $active) { return $active }
  }
  return [System.Windows.Automation.AutomationElement]::RootElement
}

function Get-CachedElement($element, $cache) {
  if ($null -eq $element) { return $null }
  try { return $element.GetUpdatedCache($cache) } catch { return $element }
}

function Enumerate-Uia($root, $limit, $query) {
  if ($null -eq $root) { return @() }
  $cache = Get-CacheRequest
  $root = Get-CachedElement $root $cache
  $results = [System.Collections.Generic.List[object]]::new()
  $needle = if ($null -ne $query) { $query.ToLowerInvariant() } else { "" }
  $rootItem = Convert-UiaElement $root
  if ($null -ne $rootItem) {
    $text = "$($rootItem.name) $($rootItem.automation_id) $($rootItem.class_name) $($rootItem.control_type)".ToLowerInvariant()
    if ([string]::IsNullOrWhiteSpace($needle) -or $text.Contains($needle)) {
      [void]$results.Add($rootItem)
    }
  }

  try {
    $descendants = $root.FindAllBuildCache(
      [System.Windows.Automation.TreeScope]::Descendants,
      [System.Windows.Automation.Condition]::TrueCondition,
      $cache
    )
    foreach ($element in $descendants) {
      if ($results.Count -ge $limit) { break }
      $item = Convert-UiaElement $element
      if ($null -eq $item) { continue }
      $text = "$($item.name) $($item.automation_id) $($item.class_name) $($item.control_type)".ToLowerInvariant()
      if ([string]::IsNullOrWhiteSpace($needle) -or $text.Contains($needle)) {
        [void]$results.Add($item)
      }
    }
  } catch {}
  return $results
}

function Find-UiaElementByRuntimeId($runtimeId) {
  if ([string]::IsNullOrWhiteSpace($runtimeId)) { return $null }
  $roots = [System.Collections.Generic.List[object]]::new()
  $activeRoot = Get-RootForScope "active"
  if ($null -ne $activeRoot) { [void]$roots.Add($activeRoot) }
  [void]$roots.Add([System.Windows.Automation.AutomationElement]::RootElement)
  foreach ($root in $roots) {
    if ($null -eq $root) { continue }
    if ((Get-UiaRuntimeIdString $root) -eq $runtimeId) { return $root }
    try {
      $walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker
      $queue = [System.Collections.Queue]::new()
      $queue.Enqueue($root)
      $seen = 0
      while ($queue.Count -gt 0 -and $seen -lt 2500) {
        $current = $queue.Dequeue()
        $seen += 1
        if ((Get-UiaRuntimeIdString $current) -eq $runtimeId) { return $current }
        $child = $walker.GetFirstChild($current)
        while ($null -ne $child) {
          $queue.Enqueue($child)
          $child = $walker.GetNextSibling($child)
        }
      }
    } catch {}
  }
  return $null
}

function Get-Pattern($element, $pattern) {
  try { return $element.GetCurrentPattern($pattern) } catch { return $null }
}

function Invoke-UiaAction($element, $operation, $text, $amount) {
  if ($null -eq $element) {
    return [pscustomobject]@{ ok = $false; message = "UIA element was not found."; operation = "" }
  }
  try {
    switch ($operation) {
      "click" {
        $pattern = Get-Pattern $element ([System.Windows.Automation.InvokePattern]::Pattern)
        if ($null -ne $pattern) { $pattern.Invoke(); return [pscustomobject]@{ ok = $true; message = "Invoked element."; operation = "Invoke" } }
        $pattern = Get-Pattern $element ([System.Windows.Automation.SelectionItemPattern]::Pattern)
        if ($null -ne $pattern) { $pattern.Select(); return [pscustomobject]@{ ok = $true; message = "Selected element."; operation = "SelectionItem" } }
        $pattern = Get-Pattern $element ([System.Windows.Automation.TogglePattern]::Pattern)
        if ($null -ne $pattern) { $pattern.Toggle(); return [pscustomobject]@{ ok = $true; message = "Toggled element."; operation = "Toggle" } }
        $pattern = Get-Pattern $element ([System.Windows.Automation.ExpandCollapsePattern]::Pattern)
        if ($null -ne $pattern) {
          if ($pattern.Current.ExpandCollapseState -eq [System.Windows.Automation.ExpandCollapseState]::Collapsed) { $pattern.Expand() } else { $pattern.Collapse() }
          return [pscustomobject]@{ ok = $true; message = "Toggled expand/collapse state."; operation = "ExpandCollapse" }
        }
        $legacySpec = $PatternSpecs | Where-Object { $_.Name -eq "LegacyIAccessible" } | Select-Object -First 1
        $pattern = if ($null -ne $legacySpec) { Get-Pattern $element $legacySpec.Pattern } else { $null }
        if ($null -ne $pattern) { $pattern.DoDefaultAction(); return [pscustomobject]@{ ok = $true; message = "Executed default accessible action."; operation = "LegacyIAccessible" } }
        return [pscustomobject]@{ ok = $false; message = "No UIA click-capable pattern was available."; operation = "" }
      }
      "set_value" {
        $pattern = Get-Pattern $element ([System.Windows.Automation.ValuePattern]::Pattern)
        if ($null -eq $pattern) { return [pscustomobject]@{ ok = $false; message = "Value pattern was not available."; operation = "" } }
        $pattern.SetValue($text)
        return [pscustomobject]@{ ok = $true; message = "Set element value."; operation = "Value" }
      }
      "select" {
        $pattern = Get-Pattern $element ([System.Windows.Automation.SelectionItemPattern]::Pattern)
        if ($null -ne $pattern) { $pattern.Select(); return [pscustomobject]@{ ok = $true; message = "Selected item."; operation = "SelectionItem" } }
        $pattern = Get-Pattern $element ([System.Windows.Automation.ExpandCollapsePattern]::Pattern)
        if ($null -ne $pattern) { $pattern.Expand(); return [pscustomobject]@{ ok = $true; message = "Expanded element."; operation = "ExpandCollapse" } }
        return [pscustomobject]@{ ok = $false; message = "No UIA selection-capable pattern was available."; operation = "" }
      }
      "scroll" {
        $pattern = Get-Pattern $element ([System.Windows.Automation.ScrollPattern]::Pattern)
        if ($null -eq $pattern) { return [pscustomobject]@{ ok = $false; message = "Scroll pattern was not available."; operation = "" } }
        $vertical = if ($amount -gt 0) { [System.Windows.Automation.ScrollAmount]::LargeDecrement } else { [System.Windows.Automation.ScrollAmount]::LargeIncrement }
        $pattern.Scroll([System.Windows.Automation.ScrollAmount]::NoAmount, $vertical)
        return [pscustomobject]@{ ok = $true; message = "Scrolled element."; operation = "Scroll" }
      }
    }
  } catch {
    return [pscustomobject]@{ ok = $false; message = $_.Exception.Message; operation = "" }
  }
  return [pscustomobject]@{ ok = $false; message = "Unsupported UIA operation."; operation = "" }
}

function Ensure-UiaSubscriptions {
  if ($null -eq $script:FocusHandler) {
    $script:FocusHandler = [System.Delegate]::CreateDelegate(
      [System.Windows.Automation.AutomationFocusChangedEventHandler],
      [AutoCruiseEventBridge].GetMethod("HandleFocusChanged")
    )
    [System.Windows.Automation.Automation]::AddAutomationFocusChangedEventHandler($script:FocusHandler)
  }

  $active = Get-ActiveWindowElement
  if ($null -eq $active) { return }
  $activeId = Get-UiaRuntimeIdString $active
  if ($activeId -eq $script:ActivePropertyRootId) { return }

  if ($null -ne $script:ActivePropertyRoot -and $null -ne $script:PropertyHandler) {
    try {
      [System.Windows.Automation.Automation]::RemoveAutomationPropertyChangedEventHandler($script:ActivePropertyRoot, $script:PropertyHandler)
    } catch {}
  }
  if ($null -ne $script:ActivePropertyRoot -and $null -ne $script:StructureHandler) {
    try {
      [System.Windows.Automation.Automation]::RemoveStructureChangedEventHandler($script:ActivePropertyRoot, $script:StructureHandler)
    } catch {}
  }

  if ($null -eq $script:PropertyHandler) {
    $script:PropertyHandler = [System.Delegate]::CreateDelegate(
      [System.Windows.Automation.AutomationPropertyChangedEventHandler],
      [AutoCruiseEventBridge].GetMethod("HandlePropertyChanged")
    )
  }
  if ($null -eq $script:StructureHandler) {
    $script:StructureHandler = [System.Delegate]::CreateDelegate(
      [System.Windows.Automation.StructureChangedEventHandler],
      [AutoCruiseEventBridge].GetMethod("HandleStructureChanged")
    )
  }

  $propertyIds = @(
    [System.Windows.Automation.AutomationElement]::NameProperty,
    [System.Windows.Automation.AutomationElement]::IsEnabledProperty,
    [System.Windows.Automation.AutomationElement]::HasKeyboardFocusProperty
  )
  try { $propertyIds += [System.Windows.Automation.ValuePattern]::ValueProperty } catch {}

  try {
    [System.Windows.Automation.Automation]::AddAutomationPropertyChangedEventHandler(
      $active,
      [System.Windows.Automation.TreeScope]::Subtree,
      $script:PropertyHandler,
      $propertyIds
    )
  } catch {}
  try {
    [System.Windows.Automation.Automation]::AddStructureChangedEventHandler(
      $active,
      [System.Windows.Automation.TreeScope]::Subtree,
      $script:StructureHandler
    )
  } catch {}

  $script:ActivePropertyRoot = $active
  $script:ActivePropertyRootId = $activeId
}

function Get-PrimarySnapshot {
  Ensure-UiaSubscriptions
  $active = Convert-UiaElement (Get-CachedElement (Get-ActiveWindowElement) (Get-CacheRequest))
  $focused = Convert-UiaElement (Get-CachedElement ([System.Windows.Automation.AutomationElement]::FocusedElement) (Get-CacheRequest))
  $events = [AutoCruiseEventBridge]::Drain()
  $counts = @{}
  foreach ($eventItem in $events) {
    $key = [string]$eventItem.type
    if (-not $counts.ContainsKey($key)) { $counts[$key] = 0 }
    $counts[$key] += 1
  }
  return [pscustomobject]@{
    available = $true
    active_window = $active
    focused_element = if ($null -ne $focused) {
      if ([string]::IsNullOrWhiteSpace($focused.name)) { "$($focused.control_type):$($focused.automation_id)" } else { "$($focused.control_type):$($focused.name)" }
    } else { "" }
    event_counts = $counts
  }
}

function Invoke-UiaOperation($operation, $params) {
  switch ($operation) {
    "primary_snapshot" { return Get-PrimarySnapshot }
    "root" { return Convert-UiaElement (Get-CachedElement ([System.Windows.Automation.AutomationElement]::RootElement) (Get-CacheRequest)) }
    "focused" { return Convert-UiaElement (Get-CachedElement ([System.Windows.Automation.AutomationElement]::FocusedElement) (Get-CacheRequest)) }
    "from_point" {
      $point = [System.Windows.Point]::new([int]$params.x, [int]$params.y)
      return Convert-UiaElement (Get-CachedElement ([System.Windows.Automation.AutomationElement]::FromPoint($point)) (Get-CacheRequest))
    }
    "active_descendants" { return Enumerate-Uia (Get-RootForScope "active") ([int]$params.limit) "" }
    "root_descendants" { return Enumerate-Uia ([System.Windows.Automation.AutomationElement]::RootElement) ([int]$params.limit) "" }
    "find" { return Enumerate-Uia (Get-RootForScope "active") ([int]$params.limit) ([string]$params.query) }
    "state" { return Convert-UiaElement (Get-CachedElement (Find-UiaElementByRuntimeId ([string]$params.element_id)) (Get-CacheRequest)) }
    "actions" {
      $element = Convert-UiaElement (Get-CachedElement (Find-UiaElementByRuntimeId ([string]$params.element_id)) (Get-CacheRequest))
      return [pscustomobject]@{ ok = $true; actions = if ($null -ne $element) { $element.patterns } else { @() } }
    }
    "click" { return Invoke-UiaAction (Find-UiaElementByRuntimeId ([string]$params.element_id)) "click" ([string]$params.text) ([int]$params.amount) }
    "set_value" { return Invoke-UiaAction (Find-UiaElementByRuntimeId ([string]$params.element_id)) "set_value" ([string]$params.text) ([int]$params.amount) }
    "select" { return Invoke-UiaAction (Find-UiaElementByRuntimeId ([string]$params.element_id)) "select" ([string]$params.text) ([int]$params.amount) }
    "scroll" { return Invoke-UiaAction (Find-UiaElementByRuntimeId ([string]$params.element_id)) "scroll" ([string]$params.text) ([int]$params.amount) }
    default { throw "Unsupported operation: $operation" }
  }
}

function Write-JsonLine($payload) {
  [Console]::Out.WriteLine(($payload | ConvertTo-Json -Compress -Depth 12))
  [Console]::Out.Flush()
}

function Start-UiaServer {
  Ensure-UiaSubscriptions
  Write-JsonLine ([pscustomobject]@{
      id = 0
      ok = $true
      result = [pscustomobject]@{ status = "ready" }
    })
  while ($true) {
    $line = [Console]::In.ReadLine()
    if ($null -eq $line) { break }
    $text = [string]$line
    if ([string]::IsNullOrWhiteSpace($text)) { continue }
    try {
      $request = $text | ConvertFrom-Json -Depth 12
      $id = [int]$request.id
      $requestOperation = [string]$request.operation
      if ($requestOperation -eq "shutdown") {
        Write-JsonLine ([pscustomobject]@{ id = $id; ok = $true; result = [pscustomobject]@{ status = "bye" } })
        break
      }
      $paramsPayload = if ($null -ne $request.params) { $request.params } else { [pscustomobject]@{} }
      $result = Invoke-UiaOperation $requestOperation $paramsPayload
      Write-JsonLine ([pscustomobject]@{ id = $id; ok = $true; result = $result })
    } catch {
      Write-JsonLine ([pscustomobject]@{
          id = if ($null -ne $request -and $null -ne $request.id) { [int]$request.id } else { -1 }
          ok = $false
          error = $_.Exception.Message
        })
    }
  }
}

if ($Operation -eq "server") {
  try {
    Start-UiaServer
    exit 0
  } catch {
    Write-JsonLine ([pscustomobject]@{ id = -1; ok = $false; error = $_.Exception.Message })
    exit 1
  }
}

try {
  $result = Invoke-UiaOperation $Operation ([pscustomobject]@{
      query = $Query
      limit = $Limit
      x = $X
      y = $Y
      element_id = $ElementId
      text = $Text
      amount = $ScrollAmount
    })
  $result | ConvertTo-Json -Compress -Depth 12
} catch {
  [pscustomobject]@{ ok = $false; message = $_.Exception.Message } | ConvertTo-Json -Compress -Depth 12
  exit 1
}
