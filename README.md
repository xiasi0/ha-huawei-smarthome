> [!WARNING]
> 本项目为非官方 Home Assistant 集成，未获得华为或相关平台的授权、认可或支持。
> 项目仅用于学习、交流与技术研究，请勿用于商业用途或其他违反适用法律、平台规则和服务条款的行为。

---

<p align="center">
  <img src="custom_components/huawei_smarthome/brand/icon.png" alt="Huawei SmartHome" width="160" />
</p>

<h1 align="center">Huawei SmartHome</h1>

<p align="center">
  <img src="https://img.shields.io/badge/Home%20Assistant-Custom%20Integration-41BDF5" alt="Home Assistant Custom Integration" />
  <img src="https://img.shields.io/badge/status-experimental-orange" alt="Experimental" />
</p>

## 项目说明

这是一个 Home Assistant 自定义集成，用于接入华为智慧生活设备。

华为 IoT 产品建模和协议在不同产品间差异较大，本项目**不提供覆盖全部产品的通用协议转换器**。仅当拥有实际设备的用户完成测试并贡献对应的单品适配器后，集成才会为该产品创建设备实体。

未提供适配器的产品不会创建实体，这是避免错误状态映射和控制命令的设计选择。

当前已接入的产品清单见[已接入设备](docs/supported-devices.md)。该清单以仓库中实际存在的 `prod_<prodId>.py` 适配器为准。

## 已接入设备

设备名称、厂商和设备类型来自华为全量 IoT 资料目录。查看当前已接入的产品列表，请参阅[已接入设备清单](docs/supported-devices.md)。

## 快速上手

### 1. 安装

#### 通过 HACS 安装

在 HACS 中进入：

```text
HACS -> 右上角菜单 -> 自定义仓库
```

添加仓库地址：

```text
https://github.com/xiasi0/ha-huawei-smarthome
```

仓库类型选择“集成（Integration）”。添加后，搜索并下载 `Huawei SmartHome`，然后重启 Home Assistant。

#### 手动安装

将 `custom_components/huawei_smarthome` 复制到 Home Assistant 配置目录：

```text
/config/custom_components/huawei_smarthome
```

复制完成后，重启 Home Assistant。

### 2. 添加集成

在 Home Assistant 中进入：

```text
设置 -> 设备与服务 -> 添加集成 -> Huawei SmartHome
```

如果列表中没有看到 `Huawei SmartHome`，请确认：

- 目录路径为 `/config/custom_components/huawei_smarthome`。
- Home Assistant 已重启。
- `manifest.json` 位于 `huawei_smarthome` 目录中。

### 3. 完成登录与家庭选择

按照页面提示输入华为账号和密码。登录成功后，选择需要接入的华为家庭。

> [!IMPORTANT]
> 设备验证仅会出现在支持华为账号登录的终端上；如出现验证，请继续输入验证码。

### 4. 查看实体

配置完成后，在 Huawei SmartHome 设备页面查看已创建的实体。实体由设备的产品适配器决定；没有适配器的产品不会显示实体。当前支持范围请以[已接入设备清单](docs/supported-devices.md)为准。

## 产品适配器贡献

欢迎拥有实际设备的用户贡献适配器。提交前请先检查[已接入设备清单](docs/supported-devices.md)，确认该 `prodId` 尚未接入。每个产品的适配器位于：

```text
custom_components/huawei_smarthome/device_adapters/prod_<产品ID>.py
```

贡献前请确保：

- 使用实际设备验证状态读取和每个控制命令。
- 根据该设备 Profile 中的字段范围、枚举值和单位进行转换，不要复用未经验证的其他产品规则。
- 提交对应测试，覆盖已验证的读取和写入行为。
- 不要提交账号、令牌、设备序列号、完整 Profile、日志或其他敏感数据。
- 新增或修改适配器后，同步更新[已接入设备清单](docs/supported-devices.md)。

适配器通过 `EntitySpec` 声明实体及其状态、属性和操作；可参考已接入清单中的 `prod_100z.py` 实现。

## 数据与隐私

本集成运行在用户自己的 Home Assistant 环境中。为完成登录和设备同步，Home Assistant 会在本地保存必要的账号会话和集成配置数据。

请妥善保护 Home Assistant 主机、备份、日志、诊断信息和 `.storage` 目录。排查问题时，请先移除账号、令牌、设备标识和其他敏感信息后再分享内容。

## 反馈问题

提交 Issue 时请说明产品 ID、Home Assistant 版本、集成版本和可脱敏的报错信息。设备协议问题请尽可能提供已脱敏的字段结构，以及实际设备上的测试结果。

## 许可证

本项目以 [GNU General Public License v3.0 only](LICENSE)（`GPL-3.0-only`）发布。
