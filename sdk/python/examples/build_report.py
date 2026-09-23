from threedx_report10 import (
    ButtonMapping,
    DirectAction,
    LiftDetection,
    PollingRate,
    Report10Config,
    WheelMode,
)


direct = ButtonMapping.direct
config = Report10Config.create(
    dpi=1600,
    lift_detection=LiftDetection.enabled_with_threshold(7),
    wheel_mode=WheelMode.INERTIAL,
    buttons=(
        direct(DirectAction.HID_MOUSE_LEFT),
        direct(DirectAction.HID_MOUSE_RIGHT),
        direct(DirectAction.HID_MOUSE_MIDDLE_OR_WHEEL_BUTTON),
        direct(DirectAction.HID_MOUSE_BACKWARD),
        direct(DirectAction.HID_MOUSE_FORWARD),
        direct(DirectAction.UNKNOWN_DIRECT_CODE_6),
        ButtonMapping.host_routed(0),
    ),
    polling_rate=PollingRate.HZ_1000,
)

print(config.to_wire_report().hex(" "))

